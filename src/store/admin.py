from django.contrib import admin
from .models import (
    BaseUnit,
    Branch,
    BranchMember,
    BranchStock,
    CustomerPayment,
    Category,
    ExchangeRate,
    Expense,
    OtherIncome,
    Products,
    Customer,
    PurchaseUnit,
    SalesProducts,
    SalesDetails,
    StockTransfer,
    Store,
    Tenant,
    TenantMember,
)
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
admin.site.register(CustomerPayment)
admin.site.register(Tenant)
admin.site.register(TenantMember)
admin.site.register(Store)
admin.site.register(Branch)
admin.site.register(BranchMember)
admin.site.register(BranchStock)
admin.site.register(StockTransfer)
