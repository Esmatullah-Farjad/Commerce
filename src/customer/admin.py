from django.contrib import admin

from .models import Customer, CustomerPayment

admin.site.register(Customer)
admin.site.register(CustomerPayment)
