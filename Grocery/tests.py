from django.contrib.auth.models import User
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
