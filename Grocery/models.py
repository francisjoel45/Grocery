# Grocery/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"

class Product(models.Model):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    buying_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_stock_level = models.DecimalField(max_digits=10, decimal_places=2, default=5)
    date_added = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
    
    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock_level
    
    @property
    def stock_value(self):
        return Decimal(str(self.quantity)) * Decimal(str(self.buying_price))

class Sale(models.Model):
    PAYMENT_CHOICES = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
    ]
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    profit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES)
    created_at = models.DateTimeField(default=timezone.now)
    sale_datetime = models.DateTimeField(default=timezone.now)
    date_sold = models.DateTimeField(default=timezone.now, blank=True, null=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    def __str__(self):
        return f"{self.product.name} - {self.quantity} kg"

    def _recalculate_sale_amounts(self):
        if not self.product_id:
            return
        quantity = Decimal(str(self.quantity))
        unit_price = Decimal(str(self.product.selling_price))
        self.unit_price = unit_price
        self.total_amount = unit_price * quantity
        self.profit = (unit_price - Decimal(str(self.product.buying_price))) * quantity

    def save(self, *args, **kwargs):
        if self.sale_datetime is None:
            self.sale_datetime = timezone.now()
        self.date_sold = self.sale_datetime

        should_recalculate = self.pk is None
        if not should_recalculate and self.product_id:
            prior_record = Sale.objects.filter(pk=self.pk).values_list(
                'product_id', 'quantity', 'unit_price', 'total_amount', 'profit'
            ).first()
            if prior_record is None:
                should_recalculate = True
            else:
                previous_product_id, previous_quantity, previous_unit_price, previous_total, previous_profit = prior_record
                current_quantity = Decimal(str(self.quantity))
                if (
                    previous_product_id != self.product_id
                    or Decimal(str(previous_quantity)) != current_quantity
                    or previous_unit_price in (None, '')
                    or previous_total in (None, '')
                    or previous_profit in (None, '')
                ):
                    should_recalculate = True

        if should_recalculate and self.product_id:
            self._recalculate_sale_amounts()

        super().save(*args, **kwargs)


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('rent', 'Rent'),
        ('utilities', 'Utilities'),
        ('transport', 'Transport'),
        ('salaries', 'Salaries'),
        ('supplies', 'Supplies'),
        ('maintenance', 'Maintenance'),
        ('other', 'Other'),
    ]

    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def __str__(self):
        return f'{self.get_category_display()} - {self.amount}'


class StockPurchase(models.Model):
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    supplier = models.CharField(max_length=200, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    purchase_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']

    def save(self, *args, **kwargs):
        self.total_cost = Decimal(str(self.quantity)) * Decimal(str(self.unit_cost))
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Stock purchase - {self.total_cost}'


class Withdrawal(models.Model):
    reason = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    withdrawal_date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-withdrawal_date', '-created_at']

    def __str__(self):
        return f'{self.reason} - {self.amount}'