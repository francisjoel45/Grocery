from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Category, Product


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
            quantity='10.00',
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
