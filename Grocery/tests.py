import csv
from io import StringIO
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from decimal import Decimal

from .models import Category, Product, Sale, Expense, StockPurchase, Withdrawal


class ProductEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='manager',
            password='test-password',
            is_staff=True,
        )
        self.category = Category.objects.create(name='Fruit')
        self.product = Product.objects.create(
            name='Apples',
            category=self.category,
            buying_price='100.00',
            selling_price='125.00',
            quantity=Decimal('10.00'),
            min_stock_level='5.00',
        )
        self.client.force_login(self.user)

    def test_edit_product_page_loads_with_existing_values(self):
        response = self.client.get(
            reverse('Grocery:edit_product', args=[self.product.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Apples"')
        self.assertContains(response, 'value="100.00"')

    def test_edit_product_updates_product(self):
        response = self.client.post(
            reverse('Grocery:edit_product', args=[self.product.pk]),
            {
                'name': 'Green Apples',
                'category': self.category.pk,
                'buying_price': '110.00',
                'selling_price': '140.00',
                'quantity': '12.50',
                'min_stock_level': '4.00',
            },
        )

        self.assertRedirects(response, reverse('Grocery:product_list'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Green Apples')
        self.assertEqual(str(self.product.quantity), '12.50')


class FinanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='finance-manager',
            password='test-password',
            is_staff=True,
        )
        self.product = Product.objects.create(
            name='Rice',
            buying_price=Decimal('80.00'),
            selling_price=Decimal('100.00'),
            quantity=Decimal('50.00'),
        )
        self.client.force_login(self.user)

    def test_finance_dashboard_calculates_profit_and_cash(self):
        Sale.objects.create(
            product=self.product,
            quantity='10.00',
            payment_method='Cash',
            added_by=self.user,
        )
        Expense.objects.create(
            category='utilities',
            description='Power',
            amount='50.00',
            recorded_by=self.user,
        )
        StockPurchase.objects.create(
            product=self.product,
            quantity='5.00',
            unit_cost='80.00',
            recorded_by=self.user,
        )
        Withdrawal.objects.create(
            reason='Owner draw',
            amount='25.00',
            recorded_by=self.user,
        )

        response = self.client.get(reverse('Grocery:finance_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['revenue'], 1000)
        self.assertEqual(response.context['gross_profit'], 200)
        self.assertEqual(response.context['net_profit'], 150)
        self.assertEqual(response.context['available_cash'], 525)

    def test_expense_form_records_entry(self):
        response = self.client.post(reverse('Grocery:add_expense'), {
            'category': 'rent',
            'description': 'Shop rent',
            'amount': '500.00',
            'expense_date': '2026-09-10',
            'notes': 'September',
        })

        self.assertRedirects(response, reverse('Grocery:finance_dashboard'))
        self.assertTrue(Expense.objects.filter(description='Shop rent').exists())


class SalesExcelImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='sales-manager',
            password='test-password',
            is_staff=True,
        )
        self.product = Product.objects.create(
            name='Rice',
            buying_price=Decimal('80.00'),
            selling_price=Decimal('100.00'),
            quantity=Decimal('50.00'),
        )
        self.client.force_login(self.user)

    def make_csv_upload(self, rows):
        output = StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Product', 'Quantity (kg)', 'Payment Method', 'Sale Date', 'Sale Time'])
        for row in rows:
            writer.writerow(row)
        return SimpleUploadedFile(
            'daily-sales.csv',
            output.getvalue().encode('utf-8-sig'),
            content_type='text/csv',
        )

    def test_import_records_each_sale_and_deducts_combined_stock(self):
        csv_file = self.make_csv_upload([
            ['rice', 2.5, 'Cash', '2026-09-15', '10:30'],
            ['Rice', 5, 'M-Pesa', None, None],
        ])

        response = self.client.post(
            reverse('Grocery:import_sales'),
            {'file': csv_file},
        )

        self.assertRedirects(response, reverse('Grocery:sales_list'))
        sales = Sale.objects.order_by('payment_method')
        self.assertEqual(sales.count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('42.50'))
        self.assertEqual(
            Sale.objects.get(payment_method='Cash').sale_datetime.date().isoformat(),
            '2026-09-15',
        )
        self.assertEqual(Sale.objects.get(payment_method='Cash').added_by, self.user)
        self.assertEqual(Sale.objects.get(payment_method='M-Pesa').total_amount, Decimal('500.00'))

    def test_import_is_all_or_nothing_when_combined_quantity_exceeds_stock(self):
        csv_file = self.make_csv_upload([
            ['Rice', 30, 'Cash', None, None],
            ['Rice', 25, 'Cash', None, None],
        ])

        response = self.client.post(reverse('Grocery:import_sales'), {'file': csv_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nothing was imported')
        self.assertContains(response, 'only 50.00 kg is available')
        self.assertEqual(Sale.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal('50.00'))

    def test_unknown_product_prevents_all_rows_from_being_imported(self):
        csv_file = self.make_csv_upload([
            ['Rice', 2, 'Cash', None, None],
            ['Unlisted item', 1, 'Cash', None, None],
        ])

        response = self.client.post(reverse('Grocery:import_sales'), {'file': csv_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'product &quot;Unlisted item&quot; was not found')
        self.assertEqual(Sale.objects.count(), 0)

    def test_invalid_csv_is_rejected_without_recording_sales(self):
        csv_file = SimpleUploadedFile(
            'broken.csv',
            b'\xff\xfe\x00\x00',
            content_type='text/csv',
        )

        response = self.client.post(reverse('Grocery:import_sales'), {'file': csv_file})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'valid UTF-8 CSV file')
        self.assertEqual(Sale.objects.count(), 0)

    def test_csv_template_download_contains_supported_column_headers(self):
        response = self.client.get(reverse('Grocery:sales_import_template'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('sales_import_template.csv', response['Content-Disposition'])
        headers = next(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(
            headers,
            ['Product', 'Quantity (kg)', 'Payment Method', 'Sale Date', 'Sale Time'],
        )

    def test_printable_pdf_template_download(self):
        response = self.client.get(reverse('Grocery:sales_import_template_pdf'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(b'%PDF-', response.content[:10])
        self.assertIn(
            'attachment; filename="sales_import_template.pdf"',
            response['Content-Disposition'],
        )
