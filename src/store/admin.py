from django.contrib import admin

from .models import (
    BaseUnit,
    BranchStock,
    Category,
    ExchangeRate,
    Expense,
    InventoryMovement,
    InventoryTransfer,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OtherIncome,
    Products,
    PurchaseUnit,
    SalesDetails,
    SalesProducts,
    StockTransfer,
    StoreStock,
    TenantStock,
)

admin.site.register(Category)
admin.site.register(Products)
admin.site.register(SalesProducts)
admin.site.register(SalesDetails)
admin.site.register(OtherIncome)
admin.site.register(Expense)
admin.site.register(BaseUnit)
admin.site.register(PurchaseUnit)
admin.site.register(ExchangeRate)
admin.site.register(BranchStock)
admin.site.register(StoreStock)
admin.site.register(TenantStock)
admin.site.register(StockTransfer)
admin.site.register(InventoryTransfer)
admin.site.register(InventoryMovement)
admin.site.register(LedgerAccount)
admin.site.register(JournalEntry)
admin.site.register(JournalLine)
