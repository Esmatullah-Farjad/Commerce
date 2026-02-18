from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import Client, TestCase
from django.urls import reverse

from .accounting import ensure_default_accounts, record_expense_entry, record_sale_entry
from .models import Branch, BranchMember, JournalLine, Store, StoreMember, Tenant, TenantMember, UserOnboarding


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
