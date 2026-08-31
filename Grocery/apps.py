# Grocery/apps.py
from django.apps import AppConfig


class GroceryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Grocery'

    def ready(self):
        from django.apps import apps
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType
        from django.db.models.signals import post_migrate

        def create_shop_attendant_group(sender, **kwargs):
            if sender.name != 'Grocery':
                return

            group, _ = Group.objects.get_or_create(name='Shop Attendant')
            Sale = apps.get_model('Grocery', 'Sale')
            Product = apps.get_model('Grocery', 'Product')

            sale_content_type = ContentType.objects.get_for_model(Sale)
            product_content_type = ContentType.objects.get_for_model(Product)

            permissions = Permission.objects.filter(
                content_type__in=[sale_content_type, product_content_type],
                codename__in=['view_sale', 'add_sale', 'change_sale', 'view_product']
            )
            group.permissions.set(permissions)

        post_migrate.connect(
            create_shop_attendant_group,
            sender=self,
            dispatch_uid='grocery_create_shop_attendant_group'
        )
