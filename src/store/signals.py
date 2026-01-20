from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ExchangeRate, Products
from decimal import Decimal

@receiver(post_save, sender=ExchangeRate)
def update_afn_prices_for_usd_products(sender, instance, created, **kwargs):
    rate = instance.usd_to_afn
    usd_products = Products.objects.filter(purchase_unit__code__iexact='usd', usd_package_sale_price__isnull=False)

    for product in usd_products:
        product.package_sale_price = round(product.usd_package_sale_price * rate, 2)
        product.item_sale_price = round(product.package_sale_price / product.package_contain, 2)
        product.save()
