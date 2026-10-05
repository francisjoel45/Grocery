# Grocery/views.py (updated with CSRF protection)
import os
import secrets
import json
import shutil
import subprocess
import tempfile
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.db import DatabaseError, transaction
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.base import DeserializationError
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncMonth
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.http import Http404
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.core.paginator import Paginator
from .models import Product, Category, Sale, Expense, StockPurchase, Withdrawal, Expense, StockPurchase, Withdrawal
from .forms import (
    ProductForm,
    CategoryForm,
    SaleForm,
    CustomPasswordChangeForm,
    AdminUserCreationForm,
    AdminUserEditForm,
    ExpenseForm,
    StockPurchaseForm,
    WithdrawalForm,
    SalesImportForm,
    DataRestoreForm,
    ExpenseForm,
    StockPurchaseForm,
    WithdrawalForm,
)
from .sales_import import SalesImportError, parse_sales_csv


def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


admin_required = user_passes_test(is_admin, login_url='Grocery:dashboard')
import csv
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io


def format_currency(value):
    return f"KSh {value:,.2f}"


def format_local_datetime(value):
    return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')


SHOP_ATTENDANT_GROUP_NAME = 'Shop Attendant'


def is_shop_attendant(user):
    return user.is_authenticated and user.groups.filter(name=SHOP_ATTENDANT_GROUP_NAME).exists()


def shop_attendant_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser or is_shop_attendant(request.user)):
            return view_func(request, *args, **kwargs)
        messages.error(request, 'This account is restricted to the sales counter only.')
        return redirect('Grocery:dashboard')
    return _wrapped


PAGE_SIZE_OPTIONS = (10, 25, 50, 100)


def paginate_queryset(request, queryset):
    try:
        page_size = int(request.GET.get('page_size', 25))
    except (TypeError, ValueError):
        page_size = 25
    if page_size not in PAGE_SIZE_OPTIONS:
        page_size = 25

    query_params = request.GET.copy()
    query_params.pop('page', None)
    paginator = Paginator(queryset, page_size)
    return paginator.get_page(request.GET.get('page')), page_size, query_params.urlencode()


@csrf_protect
@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect('Grocery:dashboard')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('Grocery:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'Grocery/login.html')


def logout_view(request):
    logout(request)
    return redirect('Grocery:login')


@never_cache
def bootstrap_admin(request, token):
    """One-time, token-protected creation of the first superuser (for shell-less hosts)."""
    expected = os.environ.get('ADMIN_SETUP_TOKEN')
    if not expected or not secrets.compare_digest(str(token), str(expected)):
        raise Http404

    if User.objects.filter(is_superuser=True).exists():
        messages.info(request, 'An administrator already exists. This setup link is now disabled.')
        return redirect('Grocery:login')

    username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
    email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
    if not username or not password:
        messages.error(
            request,
            'Set DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD in the environment first.'
        )
        return redirect('Grocery:login')

    User.objects.create_superuser(username=username, email=email, password=password)
    messages.success(
        request,
        f'Administrator "{username}" created. Log in, then remove the ADMIN_SETUP_TOKEN variable.'
    )
    return redirect('Grocery:login')

@login_required
def dashboard(request):
    if is_shop_attendant(request.user):
        today = timezone.localdate()
        recent_sales = Sale.objects.select_related('product').order_by('-sale_datetime', '-pk')[:5]
        today_sales = Sale.objects.filter(sale_datetime__date=today).aggregate(total=Sum('total_amount'))['total'] or 0
        context = {
            'is_shop_attendant': True,
            'today_sales': today_sales,
            'recent_sales': recent_sales,
        }
        return render(request, 'Grocery/dashboard.html', context)
    return _standard_dashboard(request)


def _finance_date_range(request):
        today = timezone.localdate()
        try:
            start = datetime.strptime(request.GET.get('from_date', ''), '%Y-%m-%d').date()
        except (TypeError, ValueError):
            start = today.replace(day=1)
        try:
            end = datetime.strptime(request.GET.get('to_date', ''), '%Y-%m-%d').date()
        except (TypeError, ValueError):
            end = today
        if start > end:
            start, end = end, start
        return start, end


def _finance_summary(start, end):
        sales = Sale.objects.filter(sale_datetime__date__gte=start, sale_datetime__date__lte=end)
        expenses = Expense.objects.filter(expense_date__gte=start, expense_date__lte=end)
        purchases = StockPurchase.objects.filter(purchase_date__gte=start, purchase_date__lte=end)
        withdrawals = Withdrawal.objects.filter(withdrawal_date__gte=start, withdrawal_date__lte=end)
        revenue = sales.aggregate(value=Sum('total_amount'))['value'] or Decimal('0')
        gross_profit = sales.aggregate(value=Sum('profit'))['value'] or Decimal('0')
        expense_total = expenses.aggregate(value=Sum('amount'))['value'] or Decimal('0')
        purchase_total = purchases.aggregate(value=Sum('total_cost'))['value'] or Decimal('0')
        withdrawal_total = withdrawals.aggregate(value=Sum('amount'))['value'] or Decimal('0')
        return {
            'revenue': revenue,
            'gross_profit': gross_profit,
            'expenses': expense_total,
            'stock_investment': purchase_total,
            'withdrawals': withdrawal_total,
            'net_profit': gross_profit - expense_total,
            'available_cash': revenue - expense_total - purchase_total - withdrawal_total,
            'sales_count': sales.count(),
        }


@login_required
@admin_required
def finance_dashboard(request):
        start, end = _finance_date_range(request)
        summary = _finance_summary(start, end)
        expenses = Expense.objects.filter(expense_date__gte=start, expense_date__lte=end)[:8]
        purchases = StockPurchase.objects.select_related('product').filter(
            purchase_date__gte=start, purchase_date__lte=end
        )[:8]
        withdrawals = Withdrawal.objects.filter(
            withdrawal_date__gte=start, withdrawal_date__lte=end
        )[:8]

        month_rows = []
        cursor = start.replace(day=1)
        for _ in range(6):
            if cursor > end.replace(day=1):
                break
            next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
            row = _finance_summary(cursor, next_month - timedelta(days=1))
            month_rows.append({
                'label': cursor.strftime('%b'),
                'revenue': float(row['revenue']),
                'expenses': float(row['expenses'] + row['stock_investment']),
                'profit': float(row['net_profit']),
            })
            cursor = next_month

        return render(request, 'Grocery/finance_dashboard.html', {
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'summary': summary,
            'expenses': expenses,
            'purchases': purchases,
            'withdrawals': withdrawals,
            'month_labels': [row['label'] for row in month_rows],
            'month_revenue': [row['revenue'] for row in month_rows],
            'month_expenses': [row['expenses'] for row in month_rows],
            'month_profit': [row['profit'] for row in month_rows],
            'finance_cards': [
                ('Available cash', summary['available_cash'], 'text-success' if summary['available_cash'] >= 0 else 'text-danger', 'After stock & withdrawals'),
                ('Net profit', summary['net_profit'], 'text-success' if summary['net_profit'] >= 0 else 'text-danger', 'After operating expenses'),
                ('Gross profit', summary['gross_profit'], '', 'From sales margins'),
                ('Total outflows', summary['expenses'] + summary['stock_investment'] + summary['withdrawals'], 'text-danger', 'Expenses + stock + withdrawals'),
            ],
            'expense_form': ExpenseForm(initial={'expense_date': timezone.localdate()}),
            'purchase_form': StockPurchaseForm(initial={'purchase_date': timezone.localdate()}),
            'withdrawal_form': WithdrawalForm(initial={'withdrawal_date': timezone.localdate()}),
        })


@login_required
@admin_required
def add_expense(request):
        if request.method != 'POST':
            return render(request, 'Grocery/finance_form.html', {'form': ExpenseForm(), 'title': 'Record expense', 'submit_label': 'Save expense'})
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.recorded_by = request.user
            expense.save()
            messages.success(request, 'Expense recorded and finance totals updated.')
        else:
            messages.error(request, 'Please correct the expense details and try again.')
        return redirect('Grocery:finance_dashboard')


@login_required
@admin_required
def add_stock_purchase(request):
        if request.method != 'POST':
            return render(request, 'Grocery/finance_form.html', {'form': StockPurchaseForm(), 'title': 'Record stock investment', 'submit_label': 'Save investment'})
        form = StockPurchaseForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                purchase = form.save(commit=False)
                purchase.recorded_by = request.user
                purchase.save()
                product = Product.objects.select_for_update().get(pk=purchase.product_id)
                product.quantity = F('quantity') + purchase.quantity
                product.save(update_fields=['quantity'])
        else:
            messages.error(request, 'Please correct the stock purchase details and try again.')
            return redirect('Grocery:finance_dashboard')
        messages.success(request, 'Stock investment recorded and inventory increased.')
        return redirect('Grocery:finance_dashboard')


@login_required
@admin_required
def add_withdrawal(request):
        if request.method != 'POST':
            return render(request, 'Grocery/finance_form.html', {'form': WithdrawalForm(), 'title': 'Record withdrawal', 'submit_label': 'Save withdrawal'})
        form = WithdrawalForm(request.POST)
        if form.is_valid():
            withdrawal = form.save(commit=False)
            withdrawal.recorded_by = request.user
            withdrawal.save()
            messages.success(request, 'Withdrawal recorded and available cash updated.')
        else:
            messages.error(request, 'Please correct the withdrawal details and try again.')
        return redirect('Grocery:finance_dashboard')


def _finance_export_rows(start, end):
        summary = _finance_summary(start, end)
        rows = [['Finance report', f'{start} to {end}'], [], ['Metric', 'Amount (KSh)']]
        rows += [
            ['Sales revenue', summary['revenue']],
            ['Gross profit', summary['gross_profit']],
            ['Operating expenses', summary['expenses']],
            ['Stock investment', summary['stock_investment']],
            ['Withdrawals', summary['withdrawals']],
            ['Net profit', summary['net_profit']],
            ['Available cash', summary['available_cash']],
            [],
            ['Date', 'Type', 'Description', 'Amount (KSh)'],
        ]
        for item in Expense.objects.filter(expense_date__range=(start, end)):
            rows.append([item.expense_date, 'Expense', item.description, item.amount])
        for item in StockPurchase.objects.select_related('product').filter(purchase_date__range=(start, end)):
            rows.append([item.purchase_date, 'Stock purchase', item.product.name, item.total_cost])
        for item in Withdrawal.objects.filter(withdrawal_date__range=(start, end)):
            rows.append([item.withdrawal_date, 'Withdrawal', item.description, item.amount])
        return rows


@login_required
@admin_required
def export_finance_excel(request):
        start, end = _finance_date_range(request)
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="finance-{start}-to-{end}.csv"'
        writer = csv.writer(response)
        for row in _finance_export_rows(start, end):
            writer.writerow(row)
        return response


@login_required
@admin_required
def export_finance_pdf(request):
        start, end = _finance_date_range(request)
        summary = _finance_summary(start, end)
        buffer = io.BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph(f'Finance Report: {start} to {end}', styles['Title']),
            Spacer(1, 12),
        ]
        summary_rows = [['Metric', 'Amount (KSh)']] + [
            [label, f'{summary[key]:,.2f}'] for label, key in [
                ('Sales revenue', 'revenue'), ('Gross profit', 'gross_profit'),
                ('Operating expenses', 'expenses'), ('Stock investment', 'stock_investment'),
                ('Withdrawals', 'withdrawals'), ('Net profit', 'net_profit'),
                ('Available cash', 'available_cash'),
            ]
        ]
        table = Table(summary_rows, colWidths=[300, 170])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a4d2e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d9e5dd')),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        document.build(elements)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="finance-{start}-to-{end}.pdf"'
        return response

def _standard_dashboard(request):
    products = Product.objects.all()
    total_products = products.count()
    total_stock_items = sum(p.quantity for p in products)
    low_stock = products.filter(quantity__lte=F('min_stock_level'))
    
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    today_sales = Sale.objects.filter(sale_datetime__date=today).aggregate(
        total=Sum('total_amount'), count=Sum('quantity'))
    week_sales = Sale.objects.filter(
        sale_datetime__date__gte=week_start,
        sale_datetime__date__lte=today,
    ).aggregate(
        total=Sum('total_amount'),
        profit=Sum('profit'),
        transactions=Count('pk'),
    )
    month_sales = Sale.objects.filter(sale_datetime__date__gte=month_start).aggregate(
        total=Sum('total_amount'))
    
    month_profit = Sale.objects.filter(sale_datetime__date__gte=month_start).aggregate(
        profit=Sum('profit'))
    
    low_stock_alerts = products.filter(quantity__lte=F('min_stock_level'))

    # 7-day sales trend (oldest -> newest)
    trend_start = today - timedelta(days=6)
    daily_totals = {
        row['sale_datetime__date']: row['total'] or 0
        for row in Sale.objects.filter(sale_datetime__date__gte=trend_start)
        .values('sale_datetime__date')
        .annotate(total=Sum('total_amount'))
    }
    sales_trend_labels = []
    sales_trend_data = []
    for offset in range(7):
        day = trend_start + timedelta(days=offset)
        sales_trend_labels.append(day.strftime('%a %d'))
        sales_trend_data.append(float(daily_totals.get(day, 0)))

    # Top products this month by revenue
    top_products = (
        Sale.objects.filter(sale_datetime__date__gte=month_start)
        .values('product__name')
        .annotate(total=Sum('total_amount'))
        .order_by('-total')[:5]
    )
    top_products_labels = [item['product__name'] for item in top_products]
    top_products_data = [float(item['total'] or 0) for item in top_products]

    context = {
        'is_shop_attendant': False,
        'total_products': total_products,
        'total_stock_items': total_stock_items,
        'low_stock_count': low_stock.count(),
        'today_sales': today_sales.get('total') or 0,
        'weekly_sales': week_sales.get('total') or 0,
        'weekly_transactions': week_sales.get('transactions') or 0,
        'monthly_sales': month_sales.get('total') or 0,
        'weekly_profit': week_sales.get('profit') or 0,
        'monthly_profit': month_profit.get('profit') or 0,
        'low_stock_alerts': low_stock_alerts,
        'sales_trend_labels': sales_trend_labels,
        'sales_trend_data': sales_trend_data,
        'top_products_labels': top_products_labels,
        'top_products_data': top_products_data,
    }
    return render(request, 'Grocery/dashboard.html', context)

@login_required
def product_list(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    products = Product.objects.all().order_by('name')
    search_query = request.GET.get('search')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )
    products_page, page_size, pagination_query = paginate_queryset(request, products)
    return render(request, 'Grocery/product_list.html', {
        'products': products_page,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'pagination_query': pagination_query,
    })

@login_required
def add_product(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product added successfully!')
            return redirect('Grocery:product_list')
    else:
        form = ProductForm()
    return render(request, 'Grocery/product_form.html', {'form': form, 'title': 'Add Product'})


@login_required
def add_category(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category created successfully!')
            return redirect('Grocery:product_list')
    else:
        form = CategoryForm()
    return render(request, 'Grocery/category_form.html', {'form': form})


@login_required
def edit_product(request, pk):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated successfully!')
            return redirect('Grocery:product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'Grocery/product_form.html', {'form': form, 'title': 'Edit Product'})

@login_required
def delete_product(request, pk):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted successfully!')
        return redirect('Grocery:product_list')
    return render(request, 'Grocery/product_confirm_delete.html', {'product': product})

@login_required
def update_stock(request, pk):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        try:
            new_quantity = Decimal(request.POST.get('quantity', 0))
        except (TypeError, ValueError, InvalidOperation):
            messages.error(request, 'Enter a valid quantity in kilograms.')
            return redirect('Grocery:product_list')
        if new_quantity >= 0:
            product.quantity = new_quantity
            product.save()
            messages.success(request, 'Stock updated successfully!')
        else:
            messages.error(request, 'Quantity cannot be negative.')
        return redirect('Grocery:product_list')
    return render(request, 'Grocery/update_stock.html', {'product': product})

@login_required
@shop_attendant_required
def sales_list(request):
    sales = Sale.objects.all().order_by('-sale_datetime', '-pk')
    search_query = request.GET.get('search')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if search_query:
        sales = sales.filter(product__name__icontains=search_query)
    if from_date:
        sales = sales.filter(sale_datetime__date__gte=from_date)
    if to_date:
        sales = sales.filter(sale_datetime__date__lte=to_date)
    
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    daily_sales = Sale.objects.filter(sale_datetime__date=today).aggregate(
        total=Sum('total_amount'), quantity=Sum('quantity'),
        transactions=Count('pk'), profit=Sum('profit'))
    weekly_sales = Sale.objects.filter(
        sale_datetime__date__gte=week_start,
        sale_datetime__date__lte=today,
    ).aggregate(
        total=Sum('total_amount'), transactions=Count('pk'), profit=Sum('profit'))
    monthly_sales = Sale.objects.filter(sale_datetime__date__gte=month_start).aggregate(
        total=Sum('total_amount'), count=Sum('quantity'), profit=Sum('profit'))
    
    sales_page, page_size, pagination_query = paginate_queryset(request, sales)
    context = {
        'sales': sales_page,
        'daily_sales': daily_sales,
        'weekly_sales': weekly_sales,
        'monthly_sales': monthly_sales,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'pagination_query': pagination_query,
    }
    return render(request, 'Grocery/sales_list.html', context)


@login_required
def transactions(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    transaction_totals = Sale.objects.values('payment_method').annotate(
        total=Sum('total_amount'),
        count=Count('id'),
    )
    totals_by_method = {
        item['payment_method']: item for item in transaction_totals
    }

    transactions = Sale.objects.select_related('product').order_by('-sale_datetime')
    transactions_page, page_size, pagination_query = paginate_queryset(request, transactions)
    context = {
        'cash_total': totals_by_method.get('Cash', {}).get('total') or 0,
        'cash_count': totals_by_method.get('Cash', {}).get('count') or 0,
        'mpesa_total': totals_by_method.get('M-Pesa', {}).get('total') or 0,
        'mpesa_count': totals_by_method.get('M-Pesa', {}).get('count') or 0,
        'transactions_total': Sale.objects.aggregate(
            total=Sum('total_amount')
        )['total'] or 0,
        'transactions_count': Sale.objects.count(),
        'transactions': transactions_page,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'pagination_query': pagination_query,
    }
    return render(request, 'Grocery/transactions.html', context)


@login_required
@shop_attendant_required
def add_sale(request):
    import_form = SalesImportForm()
    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            sale.added_by = request.user
            sale.sale_datetime = form.cleaned_data.get('sale_datetime', timezone.now())
            sale.date_sold = sale.sale_datetime
            product = sale.product
            if sale.quantity > product.quantity:
                messages.error(request, f"Insufficient stock available. Only {product.quantity} kg in stock.")
                return render(request, 'Grocery/sale_form.html', {
                    'form': form,
                    'import_form': import_form,
                })
            sale.save()
            product.quantity -= sale.quantity
            product.save()
            messages.success(
                request,
                f'Sale recorded successfully! Profit: {format_currency(sale.profit)}'
            )
            return redirect('Grocery:sales_list')
        import_form = SalesImportForm()
    else:
        form = SaleForm()
    return render(request, 'Grocery/sale_form.html', {
        'form': form,
        'import_form': import_form,
    })


@login_required
@shop_attendant_required
def import_sales(request):
    if request.method != 'POST':
        return redirect('Grocery:add_sale')

    form = SalesImportForm(request.POST, request.FILES)
    import_errors = []
    imported_count = 0
    if form.is_valid():
        try:
            imported_sales = parse_sales_csv(form.cleaned_data['file'])
            with transaction.atomic():
                products = list(Product.objects.select_for_update().all())
                products_by_name = {}
                for product in products:
                    products_by_name.setdefault(product.name.strip().casefold(), []).append(product)

                resolved_sales = []
                quantities_by_product = {}
                for imported_sale in imported_sales:
                    matches = products_by_name.get(imported_sale.product_name.casefold(), [])
                    if not matches:
                        import_errors.append(
                            f'Row {imported_sale.row_number}: product "{imported_sale.product_name}" was not found.'
                        )
                        continue
                    if len(matches) > 1:
                        import_errors.append(
                            f'Row {imported_sale.row_number}: product name "{imported_sale.product_name}" is ambiguous; '
                            'rename duplicate products before importing.'
                        )
                        continue

                    product = matches[0]
                    resolved_sales.append((imported_sale, product))
                    quantities_by_product[product.pk] = (
                        quantities_by_product.get(product.pk, Decimal('0')) + imported_sale.quantity
                    )

                for product in products:
                    requested_quantity = quantities_by_product.get(product.pk, Decimal('0'))
                    if requested_quantity > product.quantity:
                        import_errors.append(
                            f'Not enough stock for {product.name}: the sheet needs '
                            f'{requested_quantity} kg, but only {product.quantity} kg is available.'
                        )

                if import_errors:
                    raise SalesImportError(import_errors)

                for imported_sale, product in resolved_sales:
                    Sale.objects.create(
                        product=product,
                        quantity=imported_sale.quantity,
                        payment_method=imported_sale.payment_method,
                        sale_datetime=imported_sale.sale_datetime,
                        date_sold=imported_sale.sale_datetime,
                        added_by=request.user,
                    )
                for product in products:
                    requested_quantity = quantities_by_product.get(product.pk, Decimal('0'))
                    if requested_quantity:
                        product.quantity -= requested_quantity
                        product.save(update_fields=['quantity'])
                imported_count = len(resolved_sales)
        except SalesImportError as exc:
            import_errors = exc.errors
    else:
        import_errors = [
            f'Sales CSV: {error}'
            for field, errors in form.errors.items()
            for error in errors
        ]

    if import_errors:
        return render(request, 'Grocery/sale_form.html', {
            'form': SaleForm(),
            'import_form': form,
            'import_errors': import_errors,
        })

    messages.success(
        request,
        f'{imported_count} sale{"s" if imported_count != 1 else ""} imported successfully. '
        'Inventory and sale totals have been updated.',
    )
    return redirect('Grocery:sales_list')


@login_required
@shop_attendant_required
def sales_import_template(request):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Product', 'Quantity (kg)', 'Payment Method', 'Sale Date', 'Sale Time'])
    response = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="sales_import_template.csv"'
    return response


@login_required
@shop_attendant_required
def sales_import_template_pdf(request):
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=36,
        leftMargin=36,
        topMargin=32,
        bottomMargin=32,
        title='Sales Entry Template',
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'SalesTemplateTitle',
        parent=styles['Title'],
        textColor=colors.HexColor('#1a4d2e'),
        alignment=0,
        spaceAfter=6,
    )
    note_style = ParagraphStyle(
        'SalesTemplateNote',
        parent=styles['BodyText'],
        textColor=colors.HexColor('#475569'),
        leading=16,
    )
    table_data = [[
        'Product',
        'Quantity (kg)',
        'Payment Method',
        'Sale Date',
        'Sale Time',
    ]]
    table_data.extend([['', '', '', '', ''] for _ in range(14)])
    available_width = landscape(A4)[0] - 72
    column_widths = [
        available_width * 0.28,
        available_width * 0.16,
        available_width * 0.22,
        available_width * 0.18,
        available_width * 0.16,
    ]
    sales_table = Table(table_data, colWidths=column_widths, rowHeights=[30] + [29] * 14)
    sales_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a4d2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5d1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4f9f5')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
    ]))
    document.build([
        Paragraph('Sales Entry Template', title_style),
        Paragraph(
            'Printable worksheet: write one sale per row. Use product names exactly as they appear in inventory. '
            'Payment must be Cash or M-Pesa. Sale date is required; sale time is optional and defaults to 00:00. '
            'To import sales automatically, use the CSV template in Excel or another spreadsheet app; PDF files cannot be uploaded.',
            note_style,
        ),
        Spacer(1, 16),
        sales_table,
    ])
    response = HttpResponse(output.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="sales_import_template.pdf"'
    return response


@login_required
@admin_required
def edit_sale(request, pk):
    sale = get_object_or_404(Sale.objects.select_related('product'), pk=pk)
    if request.method == 'POST':
        form = SaleForm(request.POST, instance=sale)
        if form.is_valid():
            with transaction.atomic():
                locked_sale = Sale.objects.select_for_update().select_related('product').get(pk=pk)
                old_product = Product.objects.select_for_update().get(pk=locked_sale.product_id)
                updated_sale = form.save(commit=False)
                new_product = Product.objects.select_for_update().get(pk=updated_sale.product_id)

                old_product.quantity += locked_sale.quantity
                if new_product.pk == old_product.pk:
                    available_quantity = old_product.quantity
                else:
                    available_quantity = new_product.quantity
                if updated_sale.quantity > available_quantity:
                    form.add_error(
                        'quantity',
                        f'Insufficient stock available. Only {available_quantity} kg in stock.',
                    )
                else:
                    old_product.save(update_fields=['quantity'])
                    updated_sale.save()
                    if new_product.pk == old_product.pk:
                        new_product.quantity = old_product.quantity - updated_sale.quantity
                    else:
                        new_product.quantity -= updated_sale.quantity
                    new_product.save(update_fields=['quantity'])
                    messages.success(request, 'Sale updated successfully!')
                    return redirect('Grocery:sales_list')
    else:
        form = SaleForm(instance=sale)
    return render(request, 'Grocery/sale_form.html', {
        'form': form,
        'title': 'Edit Sale',
    })


@login_required
@admin_required
def delete_sale(request, pk):
    sale = get_object_or_404(Sale.objects.select_related('product'), pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=sale.product_id)
            product.quantity += sale.quantity
            product.save(update_fields=['quantity'])
            sale.delete()
        messages.success(request, 'Sale deleted successfully and stock restored.')
        return redirect('Grocery:sales_list')
    return render(request, 'Grocery/sale_confirm_delete.html', {'sale': sale})


@login_required
def reports(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    today = timezone.now().date()
    selected_month = request.GET.get('month')
    try:
        selected_month_date = datetime.strptime(selected_month, '%Y-%m').date() if selected_month else today
    except ValueError:
        selected_month_date = today

    month_start = selected_month_date.replace(day=1)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)

    # Weekly Report
    week_start = today - timedelta(days=today.weekday())
    weekly_sales = Sale.objects.filter(sale_datetime__date__gte=week_start)
    weekly_total = weekly_sales.aggregate(total=Sum('total_amount'))['total'] or 0
    weekly_profit = weekly_sales.aggregate(profit=Sum('profit'))['profit'] or 0
    weekly_best = weekly_sales.values('product__name').annotate(
        total=Sum('quantity')).order_by('-total')[:5]
    
    # Monthly Report
    monthly_sales = Sale.objects.filter(
        sale_datetime__date__gte=month_start,
        sale_datetime__date__lt=next_month_start,
    )
    monthly_total = monthly_sales.aggregate(total=Sum('total_amount'))['total'] or 0
    monthly_profit = monthly_sales.aggregate(profit=Sum('profit'))['profit'] or 0
    monthly_best = monthly_sales.values('product__name').annotate(
        total=Sum('quantity')).order_by('-total')[:5]
    
    context = {
        'weekly_total': weekly_total,
        'weekly_profit': weekly_profit,
        'weekly_best': weekly_best,
        'monthly_total': monthly_total,
        'monthly_profit': monthly_profit,
        'monthly_best': monthly_best,
        'selected_month': month_start.strftime('%Y-%m'),
        'selected_month_label': month_start.strftime('%b %Y'),
    }
    return render(request, 'Grocery/reports.html', context)


def _month_bounds(month_value):
    """Return timezone-aware start/end datetimes for a YYYY-MM value."""
    try:
        month_start = datetime.strptime(month_value, '%Y-%m').date()
    except (TypeError, ValueError):
        raise Http404('Invalid report month.')

    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(month_start, datetime.min.time()), tz),
        timezone.make_aware(datetime.combine(next_month, datetime.min.time()), tz),
    )


def _monthly_sales_queryset(month_value):
    start, end = _month_bounds(month_value)
    return (
        Sale.objects.select_related('product')
        .filter(sale_datetime__gte=start, sale_datetime__lt=end)
        .order_by('-sale_datetime', '-pk')
    )


@login_required
def monthly_reports(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')

    monthly_reports_data = (
        Sale.objects.annotate(month=TruncMonth(
            'sale_datetime', tzinfo=timezone.get_current_timezone()
        ))
        .values('month')
        .annotate(
            total_sales=Sum('total_amount'),
            total_profit=Sum('profit'),
            transaction_count=Count('id'),
        )
        .order_by('-month')
    )
    totals = Sale.objects.aggregate(
        total_sales=Sum('total_amount'),
        total_profit=Sum('profit'),
        transaction_count=Count('id'),
    )
    return render(request, 'Grocery/monthly_reports.html', {
        'monthly_reports': monthly_reports_data,
        'all_time_total_sales': totals['total_sales'] or 0,
        'all_time_total_profit': totals['total_profit'] or 0,
        'all_time_transaction_count': totals['transaction_count'] or 0,
    })


def _report_month_label(month_value):
    start, _ = _month_bounds(month_value)
    return timezone.localtime(start).strftime('%B %Y')


def _build_monthly_csv(month_value, sales):
    label = _report_month_label(month_value)
    total_sales = sum((sale.total_amount for sale in sales), Decimal('0'))
    total_profit = sum((sale.profit for sale in sales), Decimal('0'))
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([f'Grocery Management - Monthly Report ({label})'])
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Metric', 'Value'])
    writer.writerow(['Total sales (KSh)', f'{total_sales:.2f}'])
    writer.writerow(['Total profit (KSh)', f'{total_profit:.2f}'])
    writer.writerow(['Transaction count', len(sales)])
    writer.writerow([])
    writer.writerow(['Transactions'])
    writer.writerow([
        'Date', 'Product', 'Quantity (kg)', 'Unit price (KSh)',
        'Total sales (KSh)', 'Profit (KSh)', 'Payment method',
    ])
    for sale in sales:
        writer.writerow([
            format_local_datetime(sale.sale_datetime),
            sale.product.name,
            f'{sale.quantity:.2f}',
            f'{sale.unit_price:.2f}',
            f'{sale.total_amount:.2f}',
            f'{sale.profit:.2f}',
            sale.payment_method,
        ])
    return output.getvalue().encode('utf-8-sig')


@login_required
def export_monthly_report_pdf(request, month):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')
    sales = list(_monthly_sales_queryset(month))
    label = _report_month_label(month)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f'Grocery Management - Monthly Report: {label}', styles['Title']),
        Paragraph(
            f'Total sales: {format_currency(sum((s.total_amount for s in sales), Decimal("0")))} '
            f'| Total profit: {format_currency(sum((s.profit for s in sales), Decimal("0")))} '
            f'| Transactions: {len(sales)}',
            styles['Normal'],
        ),
        Spacer(1, 14),
    ]
    data = [['Date', 'Product', 'Quantity (kg)', 'Unit Price', 'Total Sales', 'Profit', 'Payment']]
    data.extend([
        [
            format_local_datetime(sale.sale_datetime), sale.product.name, str(sale.quantity),
            format_currency(sale.unit_price), format_currency(sale.total_amount),
            format_currency(sale.profit), sale.payment_method,
        ]
        for sale in sales
    ])
    if len(data) == 1:
        data.append(['No transactions recorded', '', '', '', '', '', ''])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(table)
    doc.build(elements)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{month}_monthly_report.pdf"'
    return response


@login_required
def export_monthly_report_csv(request, month):
    if is_shop_attendant(request.user):
        messages.error(request, 'Shop attendants can only record sales.')
        return redirect('Grocery:sales_list')
    sales = list(_monthly_sales_queryset(month))
    csv_data = _build_monthly_csv(month, sales)
    response = HttpResponse(
        csv_data,
        content_type='text/csv; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="{month}_monthly_report.csv"'
    return response


@login_required
def settings_view(request):
    from django.conf import settings as dj_settings

    database_engine = dj_settings.DATABASES.get('default', {}).get('ENGINE', '')
    return render(request, 'Grocery/settings.html', {
        'supports_postgres_backup': 'postgresql' in database_engine or 'postgis' in database_engine,
        'restore_form': DataRestoreForm(),
    })

@login_required
def change_password(request):
    if request.method == 'POST':
        form = CustomPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password was successfully updated!')
            return redirect('Grocery:settings')
    else:
        form = CustomPasswordChangeForm(request.user)
    return render(request, 'Grocery/change_password.html', {'form': form})


@login_required
@admin_required
def user_list(request):
    users = User.objects.all().order_by('username')
    search_query = request.GET.get('search')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    users_page, page_size, pagination_query = paginate_queryset(request, users)
    return render(request, 'Grocery/user_list.html', {
        'users': users_page,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'pagination_query': pagination_query,
        'total_users': User.objects.count(),
        'admin_count': User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).count(),
    })


@login_required
@admin_required
def add_user(request):
    if request.method == 'POST':
        form = AdminUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User "{user.username}" created successfully!')
            return redirect('Grocery:user_list')
    else:
        form = AdminUserCreationForm()
    return render(request, 'Grocery/user_form.html', {'form': form, 'title': 'Add User'})


@login_required
@admin_required
def edit_user(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            selected_role = form.cleaned_data.get('role')
            if user_obj == request.user and selected_role != 'staff':
                messages.error(request, 'You cannot remove your own administrator access.')
            elif user_obj == request.user and not form.cleaned_data.get('is_active'):
                messages.error(request, 'You cannot deactivate your own account.')
            else:
                form.save()
                messages.success(request, f'User "{user_obj.username}" updated successfully!')
                return redirect('Grocery:user_list')
    else:
        form = AdminUserEditForm(instance=user_obj)
    return render(request, 'Grocery/user_form.html', {
        'form': form,
        'title': 'Edit User',
        'user_obj': user_obj,
    })


@login_required
@admin_required
def delete_user(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if user_obj == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('Grocery:user_list')
    if request.method == 'POST':
        username = user_obj.username
        user_obj.delete()
        messages.success(request, f'User "{username}" deleted successfully!')
        return redirect('Grocery:user_list')
    return render(request, 'Grocery/user_confirm_delete.html', {'user_obj': user_obj})

@login_required
def export_sales_pdf(request):
    sales = Sale.objects.all().order_by('-sale_datetime')
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.darkgreen,
        spaceAfter=30
    )
    elements.append(Paragraph("Sales Report", title_style))
    elements.append(Spacer(1, 12))
    
    data = [['Date', 'Product', 'Quantity (kg)', 'Unit Price', 'Total', 'Profit', 'Payment Method']]
    for sale in sales:
        data.append([
            format_local_datetime(sale.sale_datetime),
            sale.product.name,
            str(sale.quantity),
            format_currency(sale.unit_price),
            format_currency(sale.total_amount),
            format_currency(sale.profit),
            sale.payment_method
        ])
    
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="sales_report.pdf"'
    return response

@login_required
def export_sales_excel(request):
    sales = Sale.objects.all().order_by('-sale_datetime')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sales_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Product', 'Quantity (kg)', 'Unit Price', 'Total Amount', 'Profit', 'Payment Method'])
    
    for sale in sales:
        writer.writerow([
            format_local_datetime(sale.sale_datetime),
            sale.product.name,
            sale.quantity,
            sale.unit_price,
            sale.total_amount,
            sale.profit,
            sale.payment_method
        ])
    return response


def export_period_csv(request, sales, period_name, filename):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([f'Grocery Management - {period_name} Sales'])
    writer.writerow(['Generated in Kenya (Nairobi time)'])
    writer.writerow([])
    writer.writerow([
        'Date', 'Product', 'Quantity (kg)', 'Unit Price (KSh)',
        'Total Amount (KSh)', 'Profit (KSh)', 'Payment Method'
    ])

    total_amount = Decimal('0')
    total_profit = Decimal('0')
    for sale in sales:
        writer.writerow([
            format_local_datetime(sale.sale_datetime),
            sale.product.name,
            sale.quantity,
            sale.unit_price,
            sale.total_amount,
            sale.profit,
            sale.payment_method,
        ])
        total_amount += sale.total_amount
        total_profit += sale.profit

    writer.writerow([])
    writer.writerow(['PERIOD TOTALS', '', '', '', total_amount, total_profit])
    return response


@login_required
def export_weekly_excel(request):
    today = timezone.localtime().date()
    week_start = today - timedelta(days=today.weekday())
    sales = Sale.objects.select_related('product').filter(
        sale_datetime__date__gte=week_start
    ).order_by('-sale_datetime')
    return export_period_csv(request, sales, 'Weekly', 'weekly_sales_report.csv')


@login_required
def export_monthly_excel(request):
    selected_month = request.GET.get('month')
    try:
        selected_date = datetime.strptime(selected_month, '%Y-%m').date() if selected_month else timezone.localtime().date()
    except ValueError:
        selected_date = timezone.localtime().date()

    month_start = selected_date.replace(day=1)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)

    sales = Sale.objects.select_related('product').filter(
        sale_datetime__date__gte=month_start,
        sale_datetime__date__lt=next_month_start,
    ).order_by('-sale_datetime')

    period_label = month_start.strftime('%B %Y')
    filename = f"{month_start.strftime('%Y-%m')}_sales_report.csv"
    return export_period_csv(request, sales, f'Monthly - {period_label}', filename)


@login_required
def export_transactions(request):
    transactions = Sale.objects.select_related('product').order_by('-sale_datetime')
    totals = transactions.values('payment_method').annotate(total=Sum('total_amount'))
    totals_by_method = {
        item['payment_method']: item['total'] or 0 for item in totals
    }

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions_report.csv"'
    writer = csv.writer(response)
    writer.writerow(['Transactions Report'])
    writer.writerow([])
    writer.writerow(['Payment Method', 'Total Amount (KSh)'])
    writer.writerow(['Cash', totals_by_method.get('Cash', 0)])
    writer.writerow(['M-Pesa', totals_by_method.get('M-Pesa', 0)])
    writer.writerow(['All Transactions', sum(totals_by_method.values())])
    writer.writerow([])
    writer.writerow([
        'Date', 'Product', 'Quantity', 'Unit Price (KSh)',
        'Total Amount (KSh)', 'Payment Method'
    ])

    for sale in transactions:
        writer.writerow([
            format_local_datetime(sale.sale_datetime),
            sale.product.name,
            sale.quantity,
            sale.unit_price,
            sale.total_amount,
            sale.payment_method,
        ])
    return response


@login_required
def export_products(request):
    products = Product.objects.select_related('category').order_by('name')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="products.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Name', 'Category', 'Buying Price (KSh)', 'Selling Price (KSh)',
        'Quantity (kg)', 'Min Stock Level (kg)', 'Stock Value (KSh)', 'Status', 'Date Added',
    ])
    for p in products:
        writer.writerow([
            p.name,
            p.category.name if p.category else '',
            p.buying_price,
            p.selling_price,
            p.quantity,
            p.min_stock_level,
            p.stock_value,
            'Low Stock' if p.is_low_stock else 'In Stock',
            format_local_datetime(p.date_added),
        ])
    return response


@login_required
@admin_required
def export_users(request):
    users = User.objects.all().order_by('username')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="users.csv"'
    writer = csv.writer(response)
    writer.writerow(['Username', 'First Name', 'Last Name', 'Email', 'Role', 'Active', 'Date Joined', 'Last Login'])
    for u in users:
        writer.writerow([
            u.username,
            u.first_name,
            u.last_name,
            u.email,
            'Administrator' if (u.is_staff or u.is_superuser) else 'Staff',
            'Yes' if u.is_active else 'No',
            format_local_datetime(u.date_joined) if u.date_joined else '',
            format_local_datetime(u.last_login) if u.last_login else '',
        ])
    return response


@login_required
@admin_required
def export_database(request):
    """Download a PostgreSQL SQL dump (admin only)."""
    from django.conf import settings as dj_settings

    default_db = dj_settings.DATABASES.get('default', {})
    engine = default_db.get('ENGINE', '')
    if 'postgresql' not in engine and 'postgis' not in engine:
        messages.error(request, 'A PostgreSQL backup is available only when the app is connected to PostgreSQL.')
        return redirect('Grocery:settings')

    pg_dump_path = shutil.which('pg_dump')
    if not pg_dump_path:
        messages.error(
            request,
            'PostgreSQL backup could not be created because pg_dump is not installed on the app server. '
            'Use your hosting provider’s PostgreSQL backup tools, or download the portable JSON backup.',
        )
        return redirect('Grocery:settings')

    options = default_db.get('OPTIONS', {})
    environment = os.environ.copy()
    environment.update({
        'PGHOST': str(default_db.get('HOST') or 'localhost'),
        'PGPORT': str(default_db.get('PORT') or '5432'),
        'PGDATABASE': str(default_db.get('NAME') or ''),
        'PGUSER': str(default_db.get('USER') or ''),
        'PGCONNECT_TIMEOUT': str(options.get('connect_timeout', 15)),
    })
    if default_db.get('PASSWORD'):
        environment['PGPASSWORD'] = str(default_db['PASSWORD'])
    for option in ('sslmode', 'sslcert', 'sslkey', 'sslrootcert'):
        if options.get(option):
            environment[f'PG{option.upper()}'] = str(options[option])

    try:
        result = subprocess.run(
            [
                pg_dump_path,
                '--no-owner',
                '--no-privileges',
                '--format=plain',
                '--encoding=UTF8',
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        messages.error(
            request,
            'PostgreSQL backup failed while running pg_dump. Try again or use your hosting provider’s backup tools.',
        )
        return redirect('Grocery:settings')

    if result.returncode != 0:
        messages.error(
            request,
            'PostgreSQL backup failed to connect or export the database. '
            'Check the database connection and use your hosting provider’s backup tools if needed.',
        )
        return redirect('Grocery:settings')

    filename = f"cereal-heaven-postgres-backup-{timezone.localdate().strftime('%Y%m%d')}.sql"
    response = HttpResponse(result.stdout, content_type='application/sql; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@admin_required
def export_data_json(request):
    """Portable data-only backup (works on any database engine)."""
    from io import StringIO
    buffer = StringIO()
    call_command(
        'dumpdata',
        '--natural-primary', '--natural-foreign',
        '--exclude=contenttypes', '--exclude=auth.Permission',
        '--exclude=sessions',
        '--indent=2',
        stdout=buffer,
    )
    response = HttpResponse(buffer.getvalue(), content_type='application/json')
    filename = f"cereal-heaven-data-{timezone.localdate().strftime('%Y%m%d')}.json"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@admin_required
def restore_data_json(request):
    if request.method != 'POST':
        return redirect('Grocery:settings')

    form = DataRestoreForm(request.POST, request.FILES)
    errors = []
    if form.is_valid():
        try:
            backup_contents = form.cleaned_data['file'].read().decode('utf-8-sig')
            fixture = json.loads(backup_contents)
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append('The uploaded file is not a valid UTF-8 JSON backup.')
        else:
            allowed_models = {
                'auth.user',
                'auth.group',
                'admin.logentry',
            }
            allowed_models.update(
                model._meta.label_lower.lower()
                for model in apps.get_app_config('Grocery').get_models()
            )
            if not isinstance(fixture, list) or not fixture:
                errors.append('The backup must contain a non-empty list of data records.')
            elif len(fixture) > 100000:
                errors.append('The backup contains too many records to restore safely.')
            else:
                for index, item in enumerate(fixture, start=1):
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get('model'), str)
                        or item['model'].lower() not in allowed_models
                        or not isinstance(item.get('fields'), dict)
                    ):
                        errors.append(
                            f'Record {index} references an unsupported data model.'
                        )
                        break

            if not errors:
                try:
                    with tempfile.TemporaryDirectory(prefix='grocery-restore-') as temp_dir:
                        fixture_path = os.path.join(temp_dir, 'backup.json')
                        with open(fixture_path, 'w', encoding='utf-8') as fixture_file:
                            fixture_file.write(backup_contents)
                        with transaction.atomic():
                            call_command(
                                'flush',
                                interactive=False,
                                database='default',
                                verbosity=0,
                            )
                            call_command(
                                'loaddata',
                                fixture_path,
                                database='default',
                                verbosity=0,
                            )
                except (CommandError, DeserializationError, DatabaseError, ValueError) as exc:
                    errors.append(
                        'The backup could not be restored. No changes were kept. '
                        'Check that it was created by this application and matches its data format.'
                    )

    if errors or not form.is_valid():
        if not errors:
            errors = [
                error
                for field_errors in form.errors.values()
                for error in field_errors
            ]
        from django.conf import settings as dj_settings

        return render(request, 'Grocery/settings.html', {
            'supports_postgres_backup': (
                'postgresql' in dj_settings.DATABASES.get('default', {}).get('ENGINE', '')
                or 'postgis' in dj_settings.DATABASES.get('default', {}).get('ENGINE', '')
            ),
            'restore_form': form,
            'restore_errors': errors,
        })

    request.session.flush()
    from django.conf import settings as dj_settings

    return render(request, 'Grocery/settings.html', {
        'supports_postgres_backup': (
            'postgresql' in dj_settings.DATABASES.get('default', {}).get('ENGINE', '')
            or 'postgis' in dj_settings.DATABASES.get('default', {}).get('ENGINE', '')
        ),
        'restore_form': DataRestoreForm(),
        'restore_completed': True,
    })


@login_required
def print_report(request):
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    weekly_sales = Sale.objects.filter(sale_datetime__date__gte=week_start)
    monthly_sales = Sale.objects.filter(sale_datetime__date__gte=month_start)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.darkgreen,
        spaceAfter=20
    )
    elements.append(Paragraph("Grocery Store - Report", title_style))
    
    elements.append(Paragraph("Weekly Summary", styles['Heading2']))
    elements.append(Paragraph(
        f"Total Sales: {format_currency(weekly_sales.aggregate(total=Sum('total_amount'))['total'] or 0)}",
        styles['Normal']
    ))
    elements.append(Paragraph(
        f"Total Profit: {format_currency(weekly_sales.aggregate(profit=Sum('profit'))['profit'] or 0)}",
        styles['Normal']
    ))
    
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Monthly Summary", styles['Heading2']))
    elements.append(Paragraph(
        f"Total Sales: {format_currency(monthly_sales.aggregate(total=Sum('total_amount'))['total'] or 0)}",
        styles['Normal']
    ))
    elements.append(Paragraph(
        f"Total Profit: {format_currency(monthly_sales.aggregate(profit=Sum('profit'))['profit'] or 0)}",
        styles['Normal']
    ))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="report.pdf"'
    return response


def _finance_dates(request):
    today = timezone.localdate()
    default_start = today.replace(day=1)
    try:
        start = datetime.strptime(request.GET.get('start') or request.GET.get('from_date', ''), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        start = default_start
    try:
        end = datetime.strptime(request.GET.get('end') or request.GET.get('to_date', ''), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        end = today
    if start > end:
        start, end = end, start
    return start, end


def _finance_data(start, end):
    sales = Sale.objects.filter(sale_datetime__date__range=(start, end))
    expenses = Expense.objects.filter(expense_date__range=(start, end))
    purchases = StockPurchase.objects.filter(purchase_date__range=(start, end))
    withdrawals = Withdrawal.objects.filter(withdrawal_date__range=(start, end))
    sales_totals = sales.aggregate(revenue=Sum('total_amount'), gross_profit=Sum('profit'))
    expense_total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    stock_total = purchases.aggregate(total=Sum('total_cost'))['total'] or Decimal('0')
    withdrawal_total = withdrawals.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    revenue = sales_totals['revenue'] or Decimal('0')
    gross_profit = sales_totals['gross_profit'] or Decimal('0')
    net_profit = gross_profit - expense_total
    available_cash = revenue - expense_total - stock_total - withdrawal_total
    return {
        'sales': sales,
        'expenses': expenses,
        'purchases': purchases,
        'withdrawals': withdrawals,
        'revenue': revenue,
        'gross_profit': gross_profit,
        'expense_total': expense_total,
        'stock_total': stock_total,
        'withdrawal_total': withdrawal_total,
        'net_profit': net_profit,
        'available_cash': available_cash,
    }


def _finance_access(request):
    if is_shop_attendant(request.user):
        messages.error(request, 'Finance is available to managers and administrators only.')
        return redirect('Grocery:dashboard')
    return None


@login_required
def finance_dashboard(request):
    access_response = _finance_access(request)
    if access_response:
        return access_response
    start, end = _finance_dates(request)
    data = _finance_data(start, end)
    daily_sales = {
        row['sale_datetime__date']: float(row['total'] or 0)
        for row in data['sales'].values('sale_datetime__date').annotate(total=Sum('total_amount'))
    }
    chart_labels = []
    chart_sales = []
    cursor = start
    while cursor <= end and len(chart_labels) < 31:
        chart_labels.append(cursor.strftime('%d %b'))
        chart_sales.append(daily_sales.get(cursor, 0))
        cursor += timedelta(days=1)
    expense_breakdown = list(
        data['expenses'].values('category').annotate(total=Sum('amount')).order_by('-total')
    )
    return render(request, 'Grocery/finance_dashboard.html', {
        **data,
        'start': start,
        'end': end,
        'chart_labels': chart_labels,
        'chart_sales': chart_sales,
        'expense_labels': [dict(Expense.CATEGORY_CHOICES).get(row['category'], row['category']) for row in expense_breakdown],
        'expense_data': [float(row['total'] or 0) for row in expense_breakdown],
        'recent_expenses': data['expenses'][:6],
        'recent_purchases': data['purchases'][:6],
        'recent_withdrawals': data['withdrawals'][:6],
        'finance_cards': [
            ('Available cash', data['available_cash'], 'text-success' if data['available_cash'] >= 0 else 'text-danger', 'After stock & withdrawals'),
            ('Net profit', data['net_profit'], 'text-success' if data['net_profit'] >= 0 else 'text-danger', 'After operating expenses'),
            ('Gross profit', data['gross_profit'], '', 'From sales margins'),
            ('Total outflows', data['expense_total'] + data['stock_total'] + data['withdrawal_total'], 'text-danger', 'Expenses + stock + withdrawals'),
        ],
    })


@login_required
def add_expense(request):
    access_response = _finance_access(request)
    if access_response:
        return access_response
    form = ExpenseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        expense = form.save(commit=False)
        expense.recorded_by = request.user
        expense.save()
        messages.success(request, 'Expense recorded. Finance totals updated.')
        return redirect('Grocery:finance_dashboard')
    return render(request, 'Grocery/finance_form.html', {'form': form, 'title': 'Record Expense', 'icon': 'bi-receipt-cutoff'})


@login_required
def add_stock_purchase(request):
    access_response = _finance_access(request)
    if access_response:
        return access_response
    form = StockPurchaseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            purchase = form.save(commit=False)
            purchase.recorded_by = request.user
            purchase.save()
            if purchase.product_id:
                product = Product.objects.select_for_update().get(pk=purchase.product_id)
                product.quantity = F('quantity') + purchase.quantity
                product.save(update_fields=['quantity'])
        messages.success(request, 'Stock investment recorded. Available cash updated.')
        return redirect('Grocery:finance_dashboard')
    return render(request, 'Grocery/finance_form.html', {'form': form, 'title': 'Record Stock Investment', 'icon': 'bi-box-seam'})


@login_required
def add_withdrawal(request):
    access_response = _finance_access(request)
    if access_response:
        return access_response
    form = WithdrawalForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        withdrawal = form.save(commit=False)
        withdrawal.recorded_by = request.user
        withdrawal.save()
        messages.success(request, 'Withdrawal recorded. Available cash updated.')
        return redirect('Grocery:finance_dashboard')
    return render(request, 'Grocery/finance_form.html', {'form': form, 'title': 'Record Withdrawal', 'icon': 'bi-arrow-down-right-circle'})


def _finance_export_data(request):
    start, end = _finance_dates(request)
    return start, end, _finance_data(start, end)


@login_required
def export_finance_excel(request):
    access_response = _finance_access(request)
    if access_response:
        return access_response
    start, end, data = _finance_export_data(request)
    response = HttpResponse(content_type='application/vnd.ms-excel')
    response['Content-Disposition'] = f'attachment; filename="finance-{start:%Y%m%d}-{end:%Y%m%d}.xls"'
    rows = [
        ('Finance report', f'{start:%d %b %Y} - {end:%d %b %Y}'),
        ('Sales revenue', data['revenue']),
        ('Gross profit', data['gross_profit']),
        ('Expenses', data['expense_total']),
        ('Stock investment', data['stock_total']),
        ('Withdrawals', data['withdrawal_total']),
        ('Net profit', data['net_profit']),
        ('Available cash', data['available_cash']),
        (),
        ('Date', 'Type', 'Description', 'Amount'),
    ]
    for item in data['expenses']:
        rows.append((item.expense_date, 'Expense', item.description, item.amount))
    for item in data['purchases']:
        rows.append((item.purchase_date, 'Stock investment', item.product.name if item.product else item.supplier, item.total_cost))
    for item in data['withdrawals']:
        rows.append((item.withdrawal_date, 'Withdrawal', item.reason, item.amount))
    html = ['<table>', *[f'<tr>{"".join(f"<td>{value}</td>" for value in row)}</tr>' for row in rows], '</table>']
    response.write(''.join(html))
    return response


@login_required
def export_finance_pdf(request):
    access_response = _finance_access(request)
    if access_response:
        return access_response
    start, end, data = _finance_export_data(request)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph('Cereal Heaven - Finance Report', styles['Title']),
        Paragraph(f'{start:%d %b %Y} to {end:%d %b %Y}', styles['Normal']),
        Spacer(1, 12),
    ]
    summary = [
        ['Sales revenue', 'Gross profit', 'Expenses', 'Stock investment', 'Withdrawals', 'Net profit', 'Available cash'],
        [format_currency(data['revenue']), format_currency(data['gross_profit']), format_currency(data['expense_total']),
         format_currency(data['stock_total']), format_currency(data['withdrawal_total']),
         format_currency(data['net_profit']), format_currency(data['available_cash'])],
    ]
    summary_table = Table(summary)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 14))
    detail_rows = [['Date', 'Type', 'Description', 'Amount']]
    detail_rows += [[item.expense_date.strftime('%d %b %Y'), 'Expense', item.description, format_currency(item.amount)] for item in data['expenses']]
    detail_rows += [[item.purchase_date.strftime('%d %b %Y'), 'Stock investment', item.product.name if item.product else item.supplier, format_currency(item.total_cost)] for item in data['purchases']]
    detail_rows += [[item.withdrawal_date.strftime('%d %b %Y'), 'Withdrawal', item.reason, format_currency(item.amount)] for item in data['withdrawals']]
    detail_table = Table(detail_rows, repeatRows=1, colWidths=[90, 100, 300, 100])
    detail_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f3ec')),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(detail_table)
    doc.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="finance-{start:%Y%m%d}-{end:%Y%m%d}.pdf"'
    return response