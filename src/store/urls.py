from django.urls import path

from . import views

urlpatterns = [
    path("home/", views.Home, name="home"),
    path("purchase/", views.purchase, name="purchase"),
    path("products/sale", views.products_view, name="products-view"),
    path("product/add", views.add_to_cart, name="add-to-cart"),
    path("sale/cart", views.cart_view, name="cart-view"),
    path("sale/cart/delete/<str:pid>", views.remove_cart_item, name="remove-cart-item"),
    path("product/list", views.products_display, name="products_display"),
    path("product/<int:pid>/update", views.update_products, name="update-products"),
    path("product/<int:pid>/delete", views.delete_products, name="delete-products"),
    path("product/sold", views.sold_products_view, name="sold-products-view"),
    path("product/sold/detail/<str:pk>", views.sold_product_detail, name="sold-product-detail"),
    path("sale/invoice/print/<str:sales_id>", views.print_invoice, name="print-invoice"),
    path("sales/dashboard", views.sales_dashboard, name="sales-dashboard"),
    path("dashboard/income", views.income, name="income"),
    path("dashboard/expense", views.expense, name="expense"),
    path("dashboard/summary", views.summary, name="summary"),
    path("dashboard/financial-reports", views.financial_reports, name="financial-reports"),
    path("dashboard/returned", views.returned, name="returned"),
    path("dashboard/base-unit", views.base_unit, name="base-unit"),
    path("dashboard/unit/<str:unit_id>/update", views.update_base_unit, name="update-base-unit"),
    path("dashboard/unit/<str:unit_id>/delete", views.delete_base_unit, name="delete-base-unit"),
    path("products/search", views.search_products, name="search-products"),
    path("products/return/<str:pk>", views.return_items, name="return-items"),
    path("dashboard/stock", views.stock_management, name="stock-management"),
    path("inventory/transfer", views.transfer_inventory, name="transfer-inventory"),
    path("sale/get-product-by-barcode", views.get_product_by_barcode, name="get-product-by-barcode"),
    path("sale/scanner", views.scanner_view, name="scanner-view"),
    path("sale/cart/fragment", views.cart_fragment, name="cart-fragment"),
]
