import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create the first superuser from DJANGO_SUPERUSER_* env vars if it does not already exist.'

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

        if not username or not password:
            self.stdout.write(
                'DJANGO_SUPERUSER_USERNAME/PASSWORD not set; skipping first-admin bootstrap.'
            )
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Superuser "{username}" already exists; nothing to do.')
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Superuser "{username}" created.'))
