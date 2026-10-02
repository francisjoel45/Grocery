import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.utils import timezone


MAX_SALE_ROWS = 500


class SalesImportError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(errors))


@dataclass(frozen=True)
class ImportedSale:
    row_number: int
    product_name: str
    quantity: Decimal
    payment_method: str
    sale_datetime: datetime


def _normalize_header(value):
    return ' '.join(str(value or '').strip().lower().replace('_', ' ').split())


def _parse_sale_date(value):
    return date.fromisoformat(value.strip())


def _parse_sale_time(value):
    return time.fromisoformat(value.strip())


def parse_sales_csv(uploaded_file):
    try:
        content = uploaded_file.read().decode('utf-8-sig')
        row_iterator = csv.reader(io.StringIO(content, newline=''), strict=True)
        headers = next(row_iterator, None)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise SalesImportError([
            'This file could not be read as a valid UTF-8 CSV file.'
        ]) from exc

    if not headers or not any(header.strip() for header in headers):
        raise SalesImportError(['The CSV file is empty.'])

    column_indexes = {}
    for index, value in enumerate(headers):
        normalized = _normalize_header(value)
        if normalized and normalized not in column_indexes:
            column_indexes[normalized] = index

    product_column = next(
        (column_indexes[key] for key in ('product', 'product name', 'item')
         if key in column_indexes),
        None,
    )
    quantity_column = next(
        (column_indexes[key] for key in ('quantity', 'quantity kg', 'quantity (kg)', 'qty')
         if key in column_indexes),
        None,
    )
    if product_column is None or quantity_column is None:
        raise SalesImportError([
            'The header row must include Product and Quantity columns.'
        ])

    payment_column = next(
        (column_indexes[key] for key in ('payment method', 'payment')
         if key in column_indexes),
        None,
    )
    date_column = next(
        (column_indexes[key] for key in ('sale date', 'date')
         if key in column_indexes),
        None,
    )
    time_column = next(
        (column_indexes[key] for key in ('sale time', 'time')
         if key in column_indexes),
        None,
    )

    sales = []
    errors = []
    data_row_count = 0
    try:
        for row_number, values in enumerate(row_iterator, start=2):
            if not any(value.strip() for value in values):
                continue
            data_row_count += 1
            if data_row_count > MAX_SALE_ROWS:
                errors.append(f'Row {row_number}: the CSV exceeds {MAX_SALE_ROWS} sale rows.')
                break

            def cell(column):
                return values[column] if column is not None and column < len(values) else ''

            product_name = cell(product_column).strip()
            if not product_name:
                errors.append(f'Row {row_number}: enter a product name.')
                continue

            try:
                quantity = Decimal(cell(quantity_column).strip())
                if not quantity.is_finite() or quantity <= 0:
                    raise InvalidOperation
                if quantity.as_tuple().exponent < -2 or quantity.adjusted() > 7:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                errors.append(
                    f'Row {row_number}: quantity must be a positive number with up to 2 decimal places.'
                )
                continue

            payment = cell(payment_column).strip().lower() or 'cash'
            payment_methods = {
                'cash': 'Cash',
                'm-pesa': 'M-Pesa',
                'mpesa': 'M-Pesa',
                'm pesa': 'M-Pesa',
            }
            payment_method = payment_methods.get(payment)
            if payment_method is None:
                errors.append(f'Row {row_number}: payment method must be Cash or M-Pesa.')
                continue

            sale_date_value = cell(date_column).strip()
            sale_time_value = cell(time_column).strip()
            if bool(sale_date_value) != bool(sale_time_value):
                errors.append(f'Row {row_number}: provide both Sale Date and Sale Time, or leave both blank.')
                continue
            if not sale_date_value:
                sale_datetime = timezone.now()
            else:
                try:
                    local_datetime = datetime.combine(
                        _parse_sale_date(sale_date_value),
                        _parse_sale_time(sale_time_value),
                    )
                except (TypeError, ValueError, OverflowError):
                    errors.append(
                        f'Row {row_number}: use a valid date (YYYY-MM-DD) and time (HH:MM).'
                    )
                    continue
                sale_datetime = timezone.make_aware(
                    local_datetime,
                    timezone.get_current_timezone(),
                )

            sales.append(ImportedSale(
                row_number=row_number,
                product_name=product_name,
                quantity=quantity,
                payment_method=payment_method,
                sale_datetime=sale_datetime,
            ))
    except csv.Error as exc:
        raise SalesImportError([
            'The CSV contains invalid formatting. Save it as a standard comma-separated CSV and try again.'
        ]) from exc

    if not sales and not errors:
        errors.append('The CSV contains no sale rows.')
    if errors:
        raise SalesImportError(errors)
    return sales
