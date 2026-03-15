from django.urls import path

from . import views

urlpatterns = [
    path("customer/check/", views.check_customer, name="check-customer"),
    path("customer/exits/<str:pk>", views.old_customer, name="old-customer"),
    path("sale/create/customer", views.create_customer, name="create-customer"),
    path("dashboard/customer", views.customer, name="customer"),
    path("customer/payment/<str:cid>", views.create_payment, name="create-payment"),
    path("tenancy/customers", views.customer_lists, name="customer-lists"),
]
