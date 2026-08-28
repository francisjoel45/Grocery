# Grocery/urls.py
from django.urls import path
from . import views

app_name = 'Grocery'

urlpatterns = [
    # Authentication
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('setup/<str:token>/', views.bootstrap_admin, name='bootstrap_admin'),
    
    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/categories/add/', views.add_category, name='add_category'),
    path('products/edit/<int:pk>/', views.edit_product, name='edit_product'),
    path('products/delete/<int:pk>/', views.delete_product, name='delete_product'),
    path('products/update-stock/<int:pk>/', views.update_stock, name='update_stock'),
    
    # Sales
    path('sales/', views.sales_list, name='sales_list'),
    path('sales/add/', views.add_sale, name='add_sale'),
    path('transactions/', views.transactions, name='transactions'),
    path('transactions/export/', views.export_transactions, name='export_transactions'),
    
    # Reports
    path('reports/', views.reports, name='reports'),
    path('reports/export-pdf/', views.export_sales_pdf, name='export_pdf'),
    path('reports/export-excel/', views.export_sales_excel, name='export_excel'),
    path('reports/export-weekly-excel/', views.export_weekly_excel, name='export_weekly_excel'),
    path('reports/export-monthly-excel/', views.export_monthly_excel, name='export_monthly_excel'),
    path('reports/print/', views.print_report, name='print_report'),
    
    # Settings
    path('settings/', views.settings_view, name='settings'),
    path('settings/change-password/', views.change_password, name='change_password'),

    # User management (admin only)
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.add_user, name='add_user'),
    path('users/edit/<int:pk>/', views.edit_user, name='edit_user'),
    path('users/delete/<int:pk>/', views.delete_user, name='delete_user'),
]