from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from client.models import Branch, BranchMember, Store, Tenant, TenantMember
from .models import Customer
from store.models import SalesDetails


class CustomerPhoneMatchingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="customer_match_user", password="pass123", is_active=True)
        self.tenant = Tenant.objects.create(name="Customer Tenant", slug="customer-tenant")
        self.store = Store.objects.create(tenant=self.tenant, name="Customer Store")
        self.branch = Branch.objects.create(store=self.store, name="Customer Branch")
        TenantMember.objects.create(tenant=self.tenant, user=self.user, role="staff")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_store_id"] = self.store.id
        session["active_branch_id"] = self.branch.id
        session.save()

    def test_create_customer_reuses_existing_customer_by_phone_only(self):
        existing_customer = Customer.objects.create(
            tenant=self.tenant,
            name="Ahmad",
            phone=700111222,
            address="Old Address",
        )

        response = self.client.post(
            reverse("create-customer"),
            data={
                "name": "Ahmad Khan",
                "phone": 700111222,
                "address": "New Address",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Customer.objects.filter(tenant=self.tenant, phone=700111222).count(), 1)

        existing_customer.refresh_from_db()
        self.assertEqual(existing_customer.name, "Ahmad Khan")
        self.assertEqual(existing_customer.address, "New Address")

    def test_create_customer_creates_new_record_when_phone_does_not_exist(self):
        response = self.client.post(
            reverse("create-customer"),
            data={
                "name": "New Customer",
                "phone": 799000111,
                "address": "Branch Road",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Customer.objects.filter(
                tenant=self.tenant,
                phone=799000111,
                name="New Customer",
            ).exists()
        )


class CustomerBillingStatusTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="billing_user", password="pass123", is_active=True)
        self.tenant = Tenant.objects.create(name="Billing Tenant", slug="billing-tenant")
        self.store = Store.objects.create(tenant=self.tenant, name="Billing Store")
        self.branch = Branch.objects.create(store=self.store, name="Billing Branch")
        TenantMember.objects.create(tenant=self.tenant, user=self.user, role="staff")
        BranchMember.objects.create(branch=self.branch, user=self.user, role="staff")

        self.paid_customer = Customer.objects.create(
            tenant=self.tenant,
            name="Paid Customer",
            phone=700000001,
            address="Addr 1",
        )
        self.unpaid_customer = Customer.objects.create(
            tenant=self.tenant,
            name="Unpaid Customer",
            phone=700000002,
            address="Addr 2",
        )

        self.paid_sale = SalesDetails.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            user=self.user,
            customer=self.paid_customer,
            total_amount=Decimal("500.00"),
            paid_amount=Decimal("500.00"),
            unpaid_amount=Decimal("0.00"),
        )
        self.unpaid_sale_1 = SalesDetails.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            user=self.user,
            customer=self.unpaid_customer,
            total_amount=Decimal("300.00"),
            paid_amount=Decimal("100.00"),
            unpaid_amount=Decimal("200.00"),
        )
        self.unpaid_sale_2 = SalesDetails.objects.create(
            tenant=self.tenant,
            branch=self.branch,
            user=self.user,
            customer=self.unpaid_customer,
            total_amount=Decimal("400.00"),
            paid_amount=Decimal("250.00"),
            unpaid_amount=Decimal("150.00"),
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_store_id"] = self.store.id
        session["active_branch_id"] = self.branch.id
        session.save()

    def test_customer_overview_splits_paid_and_unpaid_customers_by_aggregate_due(self):
        response = self.client.get(reverse("customer"))

        self.assertEqual(response.status_code, 200)
        unpaid_ids = {row["customer"].id for row in response.context["unpaid_customers"]}
        paid_ids = {row["customer"].id for row in response.context["paid_customers"]}

        self.assertSetEqual(unpaid_ids, {self.unpaid_customer.id})
        self.assertSetEqual(paid_ids, {self.paid_customer.id})

    def test_payment_is_allocated_across_all_unpaid_sales(self):
        response = self.client.post(
            reverse("create-payment", args=[self.unpaid_customer.id]),
            data={
                "payment_amount": "250.00",
                "payment_method": "cash",
                "note": "Partial settlement",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.unpaid_sale_1.refresh_from_db()
        self.unpaid_sale_2.refresh_from_db()

        self.assertEqual(self.unpaid_sale_1.unpaid_amount, Decimal("0.00"))
        self.assertEqual(self.unpaid_sale_2.unpaid_amount, Decimal("100.00"))

    def test_sold_product_detail_shows_customer_payment_action_when_customer_has_due(self):
        response = self.client.get(reverse("sold-product-detail", args=[self.unpaid_sale_2.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("create-payment", args=[self.unpaid_customer.id]))
