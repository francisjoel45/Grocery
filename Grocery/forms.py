# Grocery/forms.py
from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field
from .models import Product, Category, Sale

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'category', 'buying_price', 'selling_price', 'quantity', 'min_stock_level']
        labels = {
            'quantity': 'Quantity (kg)',
            'min_stock_level': 'Minimum Stock Level (kg)',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'buying_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'min_stock_level': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('name', css_class='col-md-6'),
                Column('category', css_class='col-md-6'),
                css_class='row'
            ),
            Row(
                Column('buying_price', css_class='col-md-6'),
                Column('selling_price', css_class='col-md-6'),
                css_class='row'
            ),
            Row(
                Column('quantity', css_class='col-md-6'),
                Column('min_stock_level', css_class='col-md-6'),
                css_class='row'
            ),
            Submit('submit', 'Save Product', css_class='btn btn-success mt-3')
        )


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']
        labels = {'name': 'Category name'}
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Fresh vegetables',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'name',
            Submit('submit', 'Create Category', css_class='btn btn-success mt-3')
        )


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ['product', 'quantity', 'payment_method']
        labels = {
            'quantity': 'Quantity (kg)',
        }
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'product',
            'quantity',
            'payment_method',
            Submit('submit', 'Record Sale', css_class='btn btn-success mt-3')
        )
    
    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        quantity = cleaned_data.get('quantity')
        if product and quantity:
            if quantity > product.quantity:
                raise forms.ValidationError(f"Insufficient stock available. Only {product.quantity} kg in stock.")
        return cleaned_data

class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'old_password',
            'new_password1',
            'new_password2',
            Submit('submit', 'Change Password', css_class='btn btn-success mt-3')
        )