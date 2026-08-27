# Grocery/admin.py
from django.contrib import admin
from .models import Category, Product, Sale

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'buying_price', 'selling_price', 'quantity', 'min_stock_level', 'low_stock_status']
    list_filter = ['category']  # Removed 'is_low_stock' from list_filter
    search_fields = ['name']
    list_editable = ['quantity', 'min_stock_level']
    
    def low_stock_status(self, obj):
        return obj.is_low_stock
    low_stock_status.boolean = True
    low_stock_status.short_description = 'Low Stock'
    low_stock_status.admin_order_field = 'quantity'  # Allow ordering by quantity

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['product', 'quantity', 'total_amount', 'profit', 'payment_method', 'date_sold']
    list_filter = ['payment_method', 'date_sold']
    search_fields = ['product__name']
    readonly_fields = ['unit_price', 'total_amount', 'profit']