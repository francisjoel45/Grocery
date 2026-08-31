# Grocery/views.py (updated with CSRF protection)
import os
import secrets
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.http import Http404
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.core.paginator import Paginator
from .models import Product, Category, Sale
from .forms import (
    ProductForm,
    CategoryForm,
    SaleForm,
    CustomPasswordChangeForm,
    AdminUserCreationForm,
    AdminUserEditForm,
)


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
        today = timezone.now().date()
        recent_sales = Sale.objects.select_related('product').order_by('-sale_datetime')[:5]
        today_sales = Sale.objects.filter(sale_datetime__date=today).aggregate(total=Sum('total_amount'))['total'] or 0
        context = {
            'is_shop_attendant': True,
            'today_sales': today_sales,
            'recent_sales': recent_sales,
        }
        return render(request, 'Grocery/dashboard.html', context)

    products = Product.objects.all()
    total_products = products.count()
    total_stock_items = sum(p.quantity for p in products)
    low_stock = products.filter(quantity__lte=F('min_stock_level'))
    
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    today_sales = Sale.objects.filter(sale_datetime__date=today).aggregate(
        total=Sum('total_amount'), count=Sum('quantity')) 
    week_sales = Sale.objects.filter(sale_datetime__date__gte=week_start).aggregate(
        total=Sum('total_amount'))
    month_sales = Sale.objects.filter(sale_datetime__date__gte=month_start).aggregate(
        total=Sum('total_amount'))
    
    week_profit = Sale.objects.filter(sale_datetime__date__gte=week_start).aggregate(
        profit=Sum('profit'))
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
        'monthly_sales': month_sales.get('total') or 0,
        'weekly_profit': week_profit.get('profit') or 0,
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
    sales = Sale.objects.all().order_by('-sale_datetime')
    search_query = request.GET.get('search')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if search_query:
        sales = sales.filter(product__name__icontains=search_query)
    if from_date:
        sales = sales.filter(sale_datetime__date__gte=from_date)
    if to_date:
        sales = sales.filter(sale_datetime__date__lte=to_date)
    
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    daily_sales = Sale.objects.filter(sale_datetime__date=today).aggregate(
        total=Sum('total_amount'), count=Sum('quantity'), profit=Sum('profit'))
    weekly_sales = Sale.objects.filter(sale_datetime__date__gte=week_start).aggregate(
        total=Sum('total_amount'), count=Sum('quantity'), profit=Sum('profit'))
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
        'transactions': transactions_page,
        'page_size': page_size,
        'page_size_options': PAGE_SIZE_OPTIONS,
        'pagination_query': pagination_query,
    }
    return render(request, 'Grocery/transactions.html', context)


@login_required
@shop_attendant_required
def add_sale(request):
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
                return render(request, 'Grocery/sale_form.html', {'form': form})
            sale.save()
            product.quantity -= sale.quantity
            product.save()
            messages.success(
                request,
                f'Sale recorded successfully! Profit: {format_currency(sale.profit)}'
            )
            return redirect('Grocery:sales_list')
    else:
        form = SaleForm()
    return render(request, 'Grocery/sale_form.html', {'form': form})

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

@login_required
def settings_view(request):
    return render(request, 'Grocery/settings.html')

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
            if user_obj == request.user and not form.cleaned_data.get('is_staff'):
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
    """Download the raw SQLite database file (admin only)."""
    from django.conf import settings as dj_settings
    from django.http import FileResponse

    default_db = dj_settings.DATABASES.get('default', {})
    engine = default_db.get('ENGINE', '')
    if 'sqlite' not in engine:
        messages.error(request, 'Direct database download is only available when the app uses SQLite.')
        return redirect('Grocery:settings')

    db_path = default_db.get('NAME')
    if not db_path or not os.path.exists(db_path):
        messages.error(request, 'Database file was not found on the server.')
        return redirect('Grocery:settings')

    filename = f"cereal-heaven-backup-{timezone.localdate().strftime('%Y%m%d')}.sqlite3"
    return FileResponse(open(db_path, 'rb'), as_attachment=True, filename=filename)


@login_required
@admin_required
def export_data_json(request):
    """Portable data-only backup (works on any database engine)."""
    from django.core.management import call_command
    from io import StringIO
    buffer = StringIO()
    call_command(
        'dumpdata',
        '--natural-primary', '--natural-foreign',
        '--exclude=contenttypes', '--exclude=auth.Permission',
        '--indent=2',
        stdout=buffer,
    )
    response = HttpResponse(buffer.getvalue(), content_type='application/json')
    filename = f"cereal-heaven-data-{timezone.localdate().strftime('%Y%m%d')}.json"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


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