import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'grocery_management.settings')
os.environ['DJANGO_DEBUG'] = 'True'
import django
django.setup()
from django.contrib.auth.models import User
from Grocery.models import Product, Category, Sale

Sale.objects.all().delete()
Product.objects.all().delete()
Category.objects.all().delete()
User.objects.exclude(username='admin').delete()

print('Users:', list(User.objects.values_list('username', 'is_superuser')))
print('Categories:', Category.objects.count())
print('Products:', Product.objects.count())
print('Sales:', Sale.objects.count())
