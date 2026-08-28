# Grocery/views.py (updated with CSRF protection)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.core.paginator import Paginator
from .models import Product, Category, Sale
from .forms import (
    ProductForm,
    CategoryForm,
    SaleForm,
    CustomPasswordChangeForm,
    RegistrationForm,
)
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


@csrf_protect
@never_cache
def register_view(request):
    if request.user.is_authenticated:
        return redirect('Grocery:dashboard')

    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f'Welcome to Cereal Heaven, {user.username}!')
        return redirect('Grocery:dashboard')

    return render(request, 'Grocery/register.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('Grocery:login')

@login_required
def dashboard(request):
    products = Product.objects.all()
    total_products = products.count()
    total_stock_items = sum(p.quantity for p in products)
    low_stock = products.filter(quantity__lte=F('min_stock_level'))
    
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    today_sales = Sale.objects.filter(date_sold__date=today).aggregate(
        total=Sum('total_amount'), count=Sum('quantity')) 
    week_sales = Sale.objects.filter(date_sold__date__gte=week_start).aggregate(
        total=Sum('total_amount'))
    month_sales = Sale.objects.filter(date_sold__date__gte=month_start).aggregate(
        total=Sum('total_amount'))
    
    week_profit = Sale.objects.filter(date_sold__date__gte=week_start).aggregate(
        profit=Sum('profit'))
    month_profit = Sale.objects.filter(date_sold__date__gte=month_start).aggregate(
        profit=Sum('profit'))
    
    low_stock_alerts = products.filter(quantity__lte=F('min_stock_level'))
    
    context = {
        'total_products': total_products,
        'total_stock_items': total_stock_items,
        'low_stock_count': low_stock.count(),
        'today_sales': today_sales.get('total') or 0,
        'weekly_sales': week_sales.get('total') or 0,
        'monthly_sales': month_sales.get('total') or 0,
        'weekly_profit': week_profit.get('profit') or 0,
        'monthly_profit': month_profit.get('profit') or 0,
        'low_stock_alerts': low_stock_alerts,
    }
    return render(request, 'Grocery/dashboard.html', context)

@login_required
def product_list(request):
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
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted successfully!')
        return redirect('Grocery:product_list')
    return render(request, 'Grocery/product_confirm_delete.html', {'product': product})

@login_required
def update_stock(request, pk):
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
def sales_list(request):
    sales = Sale.objects.all().order_by('-date_sold')
    search_query = request.GET.get('search')
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if search_query:
        sales = sales.filter(product__name__icontains=search_query)
    if from_date:
        sales = sales.filter(date_sold__date__gte=from_date)
    if to_date:
        sales = sales.filter(date_sold__date__lte=to_date)
    
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    daily_sales = Sale.objects.filter(date_sold__date=today).aggregate(
        total=Sum('total_amount'), count=Sum('quantity'), profit=Sum('profit'))
    weekly_sales = Sale.objects.filter(date_sold__date__gte=week_start).aggregate(
        total=Sum('total_amount'), count=Sum('quantity'), profit=Sum('profit'))
    monthly_sales = Sale.objects.filter(date_sold__date__gte=month_start).aggregate(
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
    transaction_totals = Sale.objects.values('payment_method').annotate(
        total=Sum('total_amount'),
        count=Count('id'),
    )
    totals_by_method = {
        item['payment_method']: item for item in transaction_totals
    }

    transactions = Sale.objects.select_related('product').order_by('-date_sold')
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
def add_sale(request):
    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save(commit=False)
            sale.added_by = request.user
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
    # Weekly Report
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    weekly_sales = Sale.objects.filter(date_sold__date__gte=week_start)
    weekly_total = weekly_sales.aggregate(total=Sum('total_amount'))['total'] or 0
    weekly_profit = weekly_sales.aggregate(profit=Sum('profit'))['profit'] or 0
    weekly_best = weekly_sales.values('product__name').annotate(
        total=Sum('quantity')).order_by('-total')[:5]
    
    # Monthly Report
    monthly_sales = Sale.objects.filter(date_sold__date__gte=month_start)
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
def export_sales_pdf(request):
    sales = Sale.objects.all().order_by('-date_sold')
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
            format_local_datetime(sale.date_sold),
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
    sales = Sale.objects.all().order_by('-date_sold')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sales_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Product', 'Quantity (kg)', 'Unit Price', 'Total Amount', 'Profit', 'Payment Method'])
    
    for sale in sales:
        writer.writerow([
            format_local_datetime(sale.date_sold),
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
            format_local_datetime(sale.date_sold),
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
        date_sold__date__gte=week_start
    ).order_by('-date_sold')
    return export_period_csv(request, sales, 'Weekly', 'weekly_sales_report.csv')


@login_required
def export_monthly_excel(request):
    today = timezone.localtime().date()
    month_start = today.replace(day=1)
    sales = Sale.objects.select_related('product').filter(
        date_sold__date__gte=month_start
    ).order_by('-date_sold')
    return export_period_csv(request, sales, 'Monthly', 'monthly_sales_report.csv')


@login_required
def export_transactions(request):
    transactions = Sale.objects.select_related('product').order_by('-date_sold')
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
            format_local_datetime(sale.date_sold),
            sale.product.name,
            sale.quantity,
            sale.unit_price,
            sale.total_amount,
            sale.payment_method,
        ])
    return response


@login_required
def print_report(request):
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    weekly_sales = Sale.objects.filter(date_sold__date__gte=week_start)
    monthly_sales = Sale.objects.filter(date_sold__date__gte=month_start)
    
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