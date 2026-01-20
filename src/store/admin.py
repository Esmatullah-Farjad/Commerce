from django.contrib import admin
from .models import BaseUnit, Category, ExchangeRate, Expense, OtherIncome, Products, Customer, PurchaseUnit,SalesProducts,SalesDetails
# Register your models here.

admin.site.register(Category)
admin.site.register(Products)
admin.site.register(Customer)
admin.site.register(SalesProducts)
admin.site.register(SalesDetails)
admin.site.register(OtherIncome)
admin.site.register(Expense)
admin.site.register(BaseUnit)
admin.site.register(PurchaseUnit)
admin.site.register(ExchangeRate)
