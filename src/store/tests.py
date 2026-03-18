import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import Client, TestCase
from django.urls import reverse

from .accounting import ensure_default_accounts, record_expense_entry, record_sale_entry
from .models import Branch, BranchMember, BranchStock, Category, JournalLine, Products, Store, StoreMember, Tenant, TenantMember, UserOnboarding
from .permissions import can_transfer_stock


class TenantIsolationTests(TestCase):
    def test_branch_member_requires_tenant_membership(self):
        user = User.objects.create_user(username="staff1", password="pass123")
        tenant = Tenant.objects.create(name="Tenant A", slug="tenant-a")
        store = Store.objects.create(tenant=tenant, name="Main Store")
        branch = Branch.objects.create(store=store, name="Branch 1")

        membership = BranchMember(branch=branch, user=user, role="staff")
        with self.assertRaises(ValidationError):
            membership.full_clean()


class AccountingPostingTests(TestCase):
    def test_sale_posting_creates_balanced_journal(self):
        user = User.objects.create_user(username="acc_user", password="pass123")
        tenant = Tenant.objects.create(name="Tenant B", slug="tenant-b")
        store = Store.objects.create(tenant=tenant, name="Main Store")
        branch = Branch.objects.create(store=store, name="Branch 1")
        ensure_default_accounts(tenant)

        entry = record_sale_entry(
            tenant=tenant,
            sale_total=Decimal("1000.00"),
            paid_amount=Decimal("700.00"),
            unpaid_amount=Decimal("300.00"),
            cogs_total=Decimal("400.00"),
            store=store,
            branch=branch,
            created_by=user,
            reference_id="INV-1001",
        ) 

        lines = JournalLine.objects.filter(journal_entry=entry)
        total_debit = lines.aggregate(total=Sum("debit"))["total"]
        total_credit = lines.aggregate(total=Sum("credit"))["total"]

        self.assertEqual(total_debit, total_credit)
        self.assertGreater(lines.count(), 0)


class FinancialReportScopeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="report_user", password="pass123")
        self.tenant = Tenant.objects.create(name="Tenant C", slug="tenant-c")
        self.store = Store.objects.create(tenant=self.tenant, name="Store C")
        self.branch_a = Branch.objects.create(store=self.store, name="Branch A")
        self.branch_b = Branch.objects.create(store=self.store, name="Branch B")

        TenantMember.objects.create(tenant=self.tenant, user=self.user, role="staff")
        BranchMember.objects.create(branch=self.branch_a, user=self.user, role="manager")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = self.branch_a.id
        session.save()

        record_expense_entry(
            tenant=self.tenant,
            amount=Decimal("100.00"),
            store=self.store,
            branch=self.branch_a,
            created_by=self.user,
            reference_id="E-1",
            memo="Branch A expense",
        )
        record_expense_entry(
            tenant=self.tenant,
            amount=Decimal("200.00"),
            store=self.store,
            branch=self.branch_b,
            created_by=self.user,
            reference_id="E-2",
            memo="Branch B expense",
        )

    def test_financial_reports_restricts_to_allowed_branch_scope(self):
        response = self.client.get(
            reverse("financial-reports"),
            {"scope": "branch", "branch_id": self.branch_b.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scope"], "branch")
        self.assertEqual(response.context["scope_branch"].id, self.branch_a.id)
        self.assertEqual(len(response.context["transactions"]), 1)


class OnboardingMembershipTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant = Tenant.objects.create(name="Tenant D", slug="tenant-d")
        self.store = Store.objects.create(tenant=self.tenant, name="Store D")
        self.branch = Branch.objects.create(store=self.store, name="Branch D")

    def test_activate_user_assigns_store_and_branch_memberships(self):
        admin = User.objects.create_user(username="owner_d", password="pass123", is_active=True)
        user = User.objects.create_user(username="new_staff_d", password="pass123", is_active=False)

        TenantMember.objects.create(tenant=self.tenant, user=admin, role="owner", is_owner=True)
        onboarding = UserOnboarding.objects.create(
            user=user,
            tenant=self.tenant,
            store=self.store,
            status="pending",
        )

        self.client.force_login(admin)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        response = self.client.post(reverse("activate-user", args=[onboarding.id]), {"branch": self.branch.id})
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        onboarding.refresh_from_db()

        self.assertTrue(user.is_active)
        self.assertEqual(onboarding.status, "active")
        self.assertEqual(onboarding.assigned_branch_id, self.branch.id)
        self.assertTrue(TenantMember.objects.filter(tenant=self.tenant, user=user).exists())
        self.assertTrue(StoreMember.objects.filter(store=self.store, user=user).exists())
        self.assertTrue(BranchMember.objects.filter(branch=self.branch, user=user).exists())

    def test_signin_backfills_memberships_from_pending_onboarding_for_active_user(self):
        user = User.objects.create_user(username="legacy_user_d", email="legacy@example.com", password="pass123", is_active=True)
        onboarding = UserOnboarding.objects.create(
            user=user,
            tenant=self.tenant,
            store=self.store,
            status="pending",
            assigned_branch=self.branch,
        )

        response = self.client.post(reverse("sign-in"), {"email": "legacy@example.com", "password": "pass123"})
        self.assertEqual(response.status_code, 302)
        onboarding.refresh_from_db()

        self.assertTrue(TenantMember.objects.filter(tenant=self.tenant, user=user).exists())
        self.assertTrue(StoreMember.objects.filter(store=self.store, user=user).exists())
        self.assertTrue(BranchMember.objects.filter(branch=self.branch, user=user).exists())
        self.assertEqual(onboarding.status, "active")

    def test_user_admin_activation_auto_assigns_memberships(self):
        user = User.objects.create_user(username="admin_activated_d", password="pass123", is_active=False)
        onboarding = UserOnboarding.objects.create(
            user=user,
            tenant=self.tenant,
            store=self.store,
            status="pending",
            assigned_branch=self.branch,
        )

        user.is_active = True
        user.save(update_fields=["is_active"])

        onboarding.refresh_from_db()
        self.assertEqual(onboarding.status, "active")
        self.assertTrue(TenantMember.objects.filter(tenant=self.tenant, user=user).exists())
        self.assertTrue(StoreMember.objects.filter(store=self.store, user=user).exists())
        self.assertTrue(BranchMember.objects.filter(branch=self.branch, user=user).exists())


class TenantOwnerAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username="tenant_owner_e", password="pass123", is_active=True)
        self.tenant = Tenant.objects.create(name="Tenant E", slug="tenant-e")
        self.store_a = Store.objects.create(tenant=self.tenant, name="Store A")
        self.store_b = Store.objects.create(tenant=self.tenant, name="Store B")
        self.branch_a1 = Branch.objects.create(store=self.store_a, name="Branch A1")
        self.branch_b1 = Branch.objects.create(store=self.store_b, name="Branch B1")

        TenantMember.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role="staff",
            is_owner=True,
        )
        BranchMember.objects.create(branch=self.branch_a1, user=self.owner, role="staff")

    def test_select_branch_shows_store_filter_and_owner_can_view_each_store(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        response = self.client.get(reverse("select-branch"))
        self.assertEqual(response.status_code, 200)
        store_ids = {store.id for store in response.context["stores"]}
        self.assertSetEqual(store_ids, {self.store_a.id, self.store_b.id})

        response_store_b = self.client.get(reverse("select-branch"), {"store_id": self.store_b.id})
        self.assertEqual(response_store_b.status_code, 200)
        branch_ids = {branch.id for branch in response_store_b.context["branches"]}
        self.assertSetEqual(branch_ids, {self.branch_b1.id})

    def test_owner_flag_membership_can_transfer_stock(self):
        can_transfer = can_transfer_stock(
            self.owner,
            self.tenant,
            active_branch_id=self.branch_b1.id,
        )
        self.assertTrue(can_transfer)

    def test_transfer_inventory_view_allows_owner_flag_membership(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = self.branch_b1.id
        session.save()

        response = self.client.get(reverse("transfer-inventory"))
        self.assertEqual(response.status_code, 200)

    def test_owner_can_switch_context_to_any_tenant_branch(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = self.branch_a1.id
        session["active_store_id"] = self.store_a.id
        session.save()

        response = self.client.post(
            reverse("switch-context"),
            {
                "store_id": self.store_b.id,
                "branch_id": self.branch_b1.id,
                "next": reverse("home"),
            },
        )
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        self.assertEqual(session.get("active_branch_id"), self.branch_b1.id)
        self.assertEqual(session.get("active_store_id"), self.store_b.id)

    def test_owner_signin_redirects_to_select_branch_when_multiple_branches(self):
        self.owner.email = "tenant-owner-e@example.com"
        self.owner.save(update_fields=["email"])

        response = self.client.post(
            reverse("sign-in"),
            {"email": self.owner.email, "password": "pass123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("select-branch"))

        session = self.client.session
        self.assertEqual(session.get("active_tenant_id"), self.tenant.id)
        self.assertIsNone(session.get("active_branch_id"))
        self.assertIsNone(session.get("active_store_id"))


class StaffContextScopeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="staff_scope_f", password="pass123", is_active=True)
        self.tenant = Tenant.objects.create(name="Tenant F", slug="tenant-f")
        self.store_a = Store.objects.create(tenant=self.tenant, name="Store A")
        self.store_b = Store.objects.create(tenant=self.tenant, name="Store B")
        self.branch_a1 = Branch.objects.create(store=self.store_a, name="Branch A1")
        self.branch_b1 = Branch.objects.create(store=self.store_b, name="Branch B1")
        TenantMember.objects.create(tenant=self.tenant, user=self.user, role="staff")
        BranchMember.objects.create(branch=self.branch_a1, user=self.user, role="staff")

    def test_staff_select_branch_only_lists_authorized_branches(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        response = self.client.get(reverse("select-branch"))
        self.assertEqual(response.status_code, 200)
        branch_ids = {branch.id for branch in response.context["branches"]}
        self.assertSetEqual(branch_ids, {self.branch_a1.id})

    def test_staff_store_membership_does_not_expand_branch_access(self):
        StoreMember.objects.create(store=self.store_a, user=self.user, role="staff")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session.save()

        response = self.client.get(reverse("select-branch"))

        self.assertEqual(response.status_code, 200)
        branch_ids = {branch.id for branch in response.context["branches"]}
        self.assertSetEqual(branch_ids, {self.branch_a1.id})

    def test_staff_cannot_switch_context_to_unauthorized_branch(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = self.branch_a1.id
        session["active_store_id"] = self.store_a.id
        session.save()

        response = self.client.post(
            reverse("switch-context"),
            {
                "store_id": self.store_b.id,
                "branch_id": self.branch_b1.id,
                "next": reverse("home"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("select-branch"), response.url)

        session = self.client.session
        self.assertEqual(session.get("active_branch_id"), self.branch_a1.id)
        self.assertEqual(session.get("active_store_id"), self.store_a.id)

    def test_middleware_recovers_when_only_one_allowed_branch_exists(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = self.branch_b1.id
        session["active_store_id"] = self.store_b.id
        session.save()

        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

        session = self.client.session
        self.assertEqual(session.get("active_branch_id"), self.branch_a1.id)
        self.assertEqual(session.get("active_store_id"), self.store_a.id)


class SalesContextSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="sales_staff_g", password="pass123", is_active=True)
        self.tenant = Tenant.objects.create(name="Tenant G", slug="tenant-g")
        self.store = Store.objects.create(tenant=self.tenant, name="Store G")
        self.branch = Branch.objects.create(store=self.store, name="Branch G")
        self.category = Category.objects.create(tenant=self.tenant, name="General", description="General")
        self.product = Products.objects.create(
            tenant=self.tenant,
            category=self.category,
            code=1001,
            name="Rice",
            package_contain=10,
            package_purchase_price=Decimal("500.00"),
            package_sale_price=Decimal("600.00"),
            num_of_packages=2,
            total_package_price=Decimal("1000.00"),
            item_sale_price=Decimal("60.00"),
            num_items=0,
            stock=20,
        )
        BranchStock.objects.create(
            branch=self.branch,
            product=self.product,
            stock=20,
            num_of_packages=2,
            num_items=0,
        )

        TenantMember.objects.create(tenant=self.tenant, user=self.user, role="staff")
        BranchMember.objects.create(branch=self.branch, user=self.user, role="staff")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_branch_id"] = self.branch.id
        session["active_store_id"] = self.store.id
        session.save()

    def test_add_to_cart_rejects_quantity_outside_active_branch_stock(self):
        response = self.client.post(
            reverse("add-to-cart"),
            data=json.dumps(
                {
                    "product_id": self.product.id,
                    "item_quantity": 5,
                    "package_quantity": 2,
                    "item_price": "60.00",
                    "package_price": "600.00",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("available", response.json()["message"])

    def test_barcode_lookup_rejects_products_without_stock_in_active_branch(self):
        BranchStock.objects.filter(branch=self.branch, product=self.product).update(stock=0, num_of_packages=0)

        response = self.client.post(
            reverse("get-product-by-barcode"),
            {"barcode": self.product.code},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("not available", response.json()["message"])


class BranchInventoryIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="branch_owner", password="pass123", is_active=True)
        self.tenant = Tenant.objects.create(name="Madras-Store", slug="madras-store")
        self.store = Store.objects.create(tenant=self.tenant, name="Madras-Store")
        self.branch_a = Branch.objects.create(store=self.store, name="Mohammadi Market")
        self.branch_b = Branch.objects.create(store=self.store, name="Underground Store")
        self.category = Category.objects.create(tenant=self.tenant, name="Books", description="Books")

        self.product_a = Products.objects.create(
            tenant=self.tenant,
            category=self.category,
            code=2001,
            name="Fiqh Book",
            package_contain=10,
            package_purchase_price=Decimal("100.00"),
            package_sale_price=Decimal("140.00"),
            num_of_packages=2,
            total_package_price=Decimal("200.00"),
            item_sale_price=Decimal("14.00"),
            num_items=0,
            stock=20,
        )
        self.product_b = Products.objects.create(
            tenant=self.tenant,
            category=self.category,
            code=2002,
            name="Hadith Book",
            package_contain=10,
            package_purchase_price=Decimal("120.00"),
            package_sale_price=Decimal("160.00"),
            num_of_packages=1,
            total_package_price=Decimal("120.00"),
            item_sale_price=Decimal("16.00"),
            num_items=0,
            stock=10,
        )

        BranchStock.objects.create(
            branch=self.branch_a,
            product=self.product_a,
            stock=20,
            num_of_packages=2,
            num_items=0,
        )
        BranchStock.objects.create(
            branch=self.branch_b,
            product=self.product_b,
            stock=10,
            num_of_packages=1,
            num_items=0,
        )

        TenantMember.objects.create(tenant=self.tenant, user=self.user, role="owner")
        BranchMember.objects.create(branch=self.branch_a, user=self.user, role="manager")
        BranchMember.objects.create(branch=self.branch_b, user=self.user, role="manager")

        self.client.force_login(self.user)

    def _set_active_branch(self, branch):
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_store_id"] = self.store.id
        session["active_branch_id"] = branch.id
        session.save()

    def test_products_display_only_shows_products_for_active_branch(self):
        self._set_active_branch(self.branch_b)

        response = self.client.get(reverse("products_display"))

        self.assertEqual(response.status_code, 200)
        products = list(response.context["page_obj"].object_list)
        self.assertEqual([product.id for product in products], [self.product_b.id])
        self.assertContains(response, "Hadith Book")
        self.assertNotContains(response, "Fiqh Book")

    def test_branch_to_branch_transfer_updates_destination_branch_stock(self):
        self._set_active_branch(self.branch_a)

        response = self.client.post(
            reverse("transfer-inventory"),
            data={
                "product": self.product_a.id,
                "to_scope": "branch",
                "to_branch": self.branch_b.id,
                "package_qty": 1,
                "item_qty": 0,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        source_stock = BranchStock.objects.get(branch=self.branch_a, product=self.product_a)
        destination_stock = BranchStock.objects.get(branch=self.branch_b, product=self.product_a)

        self.assertEqual(source_stock.stock, 10)
        self.assertEqual(source_stock.num_of_packages, 1)
        self.assertEqual(destination_stock.stock, 10)
        self.assertEqual(destination_stock.num_of_packages, 1)
