# Grocery Management System

A Django-based grocery inventory and sales management system for tracking products, stock, kilogram-based sales, payments, and business performance.

## Features

- Product and category management
- Stock tracking in kilograms, including decimal quantities
- Sales recording with Cash and M-Pesa payment methods
- Bulk sale recording from Excel-compatible `.csv` files using a downloadable template
- Admin-only portable JSON data backups with transactional restore from Settings
- Automatic sales totals and profit calculations
- Transactions page with payment-method summaries
- Weekly and monthly business reports
- CSV exports that open in Excel
- Nairobi, Kenya timezone support
- Responsive desktop and mobile interface
- Collapsible mobile navigation
- Modern login and self-service registration
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

## Deploying to Railway

For Railway, set a PostgreSQL database first, then add this environment variable in the service settings:

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
```

Railway usually injects the value automatically when a PostgreSQL service is linked, but if it does not, paste the full Postgres connection string into the service environment.

After deployment, run:

```bash
python manage.py migrate
python manage.py createsuperuser
```

## Main pages

- `/` - secure login
- `/dashboard/` - business overview
- `/products/` - products and categories
- `/sales/` - sales records
- `/transactions/` - Cash and M-Pesa transaction totals
- `/reports/` - weekly/monthly reporting and CSV exports
- `/users/` - user management (administrators only)
- `/admin/` - Django administration

## Currency and timezone

The system uses Kenyan shillings (`KSh`) and the `Africa/Nairobi` timezone.

## Data backups and recovery

Administrators can download a portable JSON data backup from **Settings > Backups**.
On PostgreSQL deployments, the settings page also offers a full `.sql` database dump
created by PostgreSQL's `pg_dump` utility. The utility must be installed on the app server;
if it is unavailable, use the hosting provider's PostgreSQL backup tools or the portable
JSON data backup to restore application data.
Restoring JSON replaces existing users and business records, requires explicit confirmation,
and signs the administrator out after a successful restore. Download and keep a recent backup
before restoring.

## Notes

The SQLite database is local development data and is intentionally excluded from Git. Create a new database by running migrations after cloning.
