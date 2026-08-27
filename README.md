# Grocery Management System

A Django-based grocery inventory and sales management system for tracking products, stock, kilogram-based sales, payments, and business performance.

## Features

- Product and category management
- Stock tracking in kilograms, including decimal quantities
- Sales recording with Cash and M-Pesa payment methods
- Automatic sales totals and profit calculations
- Transactions page with payment-method summaries
- Weekly and monthly business reports
- CSV exports that open in Excel
- Nairobi, Kenya timezone support
- Responsive desktop and mobile interface
- Collapsible mobile navigation
- User authentication and password management

## Requirements

- Python 3.11 or newer
- Django

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/francisjoel45/Grocery.git
   cd Grocery
   ```

2. Create and activate a virtual environment:

   **Windows PowerShell**

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Apply database migrations:

   ```bash
   python manage.py migrate
   ```

5. Create an administrator account:

   ```bash
   python manage.py createsuperuser
   ```

6. Start the development server:

   ```bash
   python manage.py runserver
   ```

Open `http://127.0.0.1:8000/` in your browser.

## Deploying to Render

This repository includes `render.yaml` for deploying the Django web service with a
managed PostgreSQL database:

1. Push the repository to GitHub.
2. In Render, choose **New + > Blueprint**.
3. Select the GitHub repository and deploy the blueprint.
4. After deployment, create an admin user from the Render Shell:

   ```bash
   python manage.py createsuperuser
   ```

Render runs migrations and collects static files during each deployment.

## Main pages

- `/dashboard/` - business overview
- `/products/` - products and categories
- `/sales/` - sales records
- `/transactions/` - Cash and M-Pesa transaction totals
- `/reports/` - weekly/monthly reporting and CSV exports
- `/admin/` - Django administration

## Currency and timezone

The system uses Kenyan shillings (`KSh`) and the `Africa/Nairobi` timezone.

## Notes

The SQLite database is local development data and is intentionally excluded from Git. Create a new database by running migrations after cloning.
