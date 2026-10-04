import csv
from datetime import date, datetime, timedelta
from io import StringIO
from unittest.mock import patch
from django.contrib.auth.models import Group, Permission, User
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
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

    def test_sale_keeps_original_price_and_profit_after_product_price_changes(self):
        sale = Sale.objects.create(
            product=self.product,
            quantity='10.00',
            payment_method='Cash',
            added_by=self.user,
        )

        self.product.selling_price = Decimal('150.00')
        self.product.buying_price = Decimal('90.00')
        self.product.save(update_fields=['selling_price', 'buying_price'])

        sale.refresh_from_db()
        self.assertEqual(sale.unit_price, Decimal('100.00'))
        self.assertEqual(sale.total_amount, Decimal('1000.00'))
        self.assertEqual(sale.profit, Decimal('200.00'))

    def test_transactions_page_count_increases_with_recorded_sales(self):
        Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            added_by=self.user,
        )
        Sale.objects.create(
            product=self.product,
            quantity='2.00',
            payment_method='M-Pesa',
            added_by=self.user,
        )

        response = self.client.get(reverse('Grocery:transactions'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['transactions_count'], 2)

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


class SalesListOrderingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='sales-list-manager',
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

    def test_sales_list_shows_newest_sale_first_and_breaks_timestamp_ties(self):
        now = timezone.now()
        oldest = Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            sale_datetime=now - timedelta(days=1),
        )
        earlier_tied_sale = Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            sale_datetime=now,
        )
        later_tied_sale = Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            sale_datetime=now,
        )

        response = self.client.get(reverse('Grocery:sales_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [sale.pk for sale in response.context['sales']],
            [later_tied_sale.pk, earlier_tied_sale.pk, oldest.pk],
        )

    def test_weekly_summary_includes_only_sales_from_this_week_through_today(self):
        today = date(2026, 10, 4)
        for sale_date in (
            datetime(2026, 9, 27, 12),
            datetime(2026, 9, 28, 12),
            datetime(2026, 10, 4, 12),
            datetime(2026, 10, 5, 12),
        ):
            Sale.objects.create(
                product=self.product,
                quantity='1.00',
                payment_method='Cash',
                sale_datetime=timezone.make_aware(sale_date),
            )

        with patch('Grocery.views.timezone.localdate', return_value=today):
            response = self.client.get(reverse('Grocery:sales_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['weekly_sales']['transactions'], 2)
        self.assertEqual(response.context['weekly_sales']['total'], Decimal('200.00'))
        self.assertContains(response, '2 transactions')

    def test_weekly_summary_is_zero_when_no_sales_were_recorded_this_week(self):
        today = date(2026, 10, 4)
        Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            sale_datetime=timezone.make_aware(datetime(2026, 9, 27, 12)),
        )

        with patch('Grocery.views.timezone.localdate', return_value=today):
            response = self.client.get(reverse('Grocery:sales_list'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['weekly_sales']['total'])
        self.assertEqual(response.context['weekly_sales']['transactions'], 0)
        self.assertContains(response, 'KSh 0.00')

    def test_attendant_dashboard_lists_latest_sales_first(self):
        attendant_group, _ = Group.objects.get_or_create(name='Shop Attendant')
        self.user.groups.add(attendant_group)
        now = timezone.now()
        oldest = Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            sale_datetime=now - timedelta(days=1),
        )
        latest = Sale.objects.create(
            product=self.product,
            quantity='1.00',
            payment_method='Cash',
            sale_datetime=now,
        )

        response = self.client.get(reverse('Grocery:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [sale.pk for sale in response.context['recent_sales']],
            [latest.pk, oldest.pk],
        )


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


class DataBackupRestoreTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(
            username='backup-admin',
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

    def test_settings_show_postgresql_backup_for_postgresql(self):
        with patch.dict(
            settings.DATABASES['default'],
            {'ENGINE': 'django.db.backends.postgresql'},
        ):
            response = self.client.get(reverse('Grocery:settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Download PostgreSQL Backup (.sql)')
        self.assertNotContains(response, 'Download SQLite File')

    def test_postgresql_backup_download_returns_pg_dump_output(self):
        fake_dump = type('DumpResult', (), {
            'returncode': 0,
            'stdout': b'-- PostgreSQL database dump\\n',
            'stderr': b'',
        })()
        database_config = settings.DATABASES['default']
        with patch.dict(database_config, {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'grocery_db',
            'USER': 'grocery_user',
            'PASSWORD': 'db-secret',
            'HOST': 'database.example',
            'PORT': '5432',
            'OPTIONS': {'sslmode': 'require'},
        }):
            with patch('Grocery.views.shutil.which', return_value='pg_dump.exe'):
                with patch('Grocery.views.subprocess.run', return_value=fake_dump) as run_dump:
                    response = self.client.get(reverse('Grocery:export_database'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/sql; charset=utf-8')
        self.assertIn('cereal-heaven-postgres-backup-', response['Content-Disposition'])
        self.assertTrue(response['Content-Disposition'].endswith('.sql"'))
        self.assertEqual(response.content, fake_dump.stdout)
        args, kwargs = run_dump.call_args
        self.assertEqual(args[0][0], 'pg_dump.exe')
        self.assertEqual(kwargs['env']['PGHOST'], 'database.example')
        self.assertEqual(kwargs['env']['PGDATABASE'], 'grocery_db')
        self.assertEqual(kwargs['env']['PGPASSWORD'], 'db-secret')
        self.assertEqual(kwargs['env']['PGSSLMODE'], 'require')
        self.assertNotIn('db-secret', args[0])

    def test_postgresql_backup_reports_missing_pg_dump(self):
        with patch.dict(
            settings.DATABASES['default'],
            {'ENGINE': 'django.db.backends.postgresql'},
        ):
            with patch('Grocery.views.shutil.which', return_value=None):
                response = self.client.get(reverse('Grocery:export_database'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'pg_dump is not installed')

    def test_admin_can_download_and_restore_portable_data_backup(self):
        attendant_group, _ = Group.objects.get_or_create(name='Shop Attendant')
        sale_permission = Permission.objects.get(
            codename='add_sale',
            content_type__app_label='Grocery',
        )
        attendant_group.permissions.add(sale_permission)
        self.user.groups.add(attendant_group)

        backup_response = self.client.get(reverse('Grocery:export_data_json'))
        self.assertEqual(backup_response.status_code, 200)
        self.assertEqual(backup_response['Content-Type'], 'application/json')

        self.product.name = 'Changed after backup'
        self.product.save(update_fields=['name'])
        Product.objects.create(
            name='New item',
            buying_price='10.00',
            selling_price='20.00',
            quantity='3.00',
        )
        backup_file = SimpleUploadedFile(
            'cereal-heaven-data.json',
            backup_response.content,
            content_type='application/json',
        )

        response = self.client.post(
            reverse('Grocery:restore_data_json'),
            {'file': backup_file, 'confirm_restore': 'on'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('restore_errors'), response.context.get('restore_errors'))
        self.assertContains(response, 'Backup restored successfully')
        self.assertEqual(Product.objects.count(), 1)
        self.assertTrue(Product.objects.filter(name='Rice', quantity='50.00').exists())
        self.assertTrue(User.objects.filter(username='backup-admin').exists())
        self.assertTrue(
            User.objects.get(username='backup-admin').groups.filter(name='Shop Attendant').exists()
        )
        self.assertFalse(Product.objects.filter(name='New item').exists())

    def test_restore_requires_explicit_confirmation(self):
        backup_file = SimpleUploadedFile(
            'backup.json',
            b'[]',
            content_type='application/json',
        )

        response = self.client.post(
            reverse('Grocery:restore_data_json'),
            {'file': backup_file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertEqual(Product.objects.count(), 1)

    def test_invalid_backup_does_not_change_existing_data(self):
        backup_file = SimpleUploadedFile(
            'broken.json',
            b'not json',
            content_type='application/json',
        )

        response = self.client.post(
            reverse('Grocery:restore_data_json'),
            {'file': backup_file, 'confirm_restore': 'on'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not a valid UTF-8 JSON backup')
        self.assertEqual(Product.objects.count(), 1)
        self.assertTrue(Product.objects.filter(name='Rice').exists())

    def test_failed_fixture_load_rolls_back_the_data_flush(self):
        backup_file = SimpleUploadedFile(
            'invalid-record.json',
            b'[{"model":"grocery.product","pk":1,"fields":{"not_a_field":"value"}}]',
            content_type='application/json',
        )

        response = self.client.post(
            reverse('Grocery:restore_data_json'),
            {'file': backup_file, 'confirm_restore': 'on'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No changes were kept')
        self.assertEqual(Product.objects.count(), 1)
        self.assertTrue(Product.objects.filter(name='Rice').exists())
