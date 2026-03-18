from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import Branch, BranchMember, Store, StoreMember, Tenant, TenantMember


class BranchManagementViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username="owner_user", password="pass123", is_active=True)
        self.staff = User.objects.create_user(username="staff_user", password="pass123", is_active=True)
        self.employee = User.objects.create_user(username="employee_user", password="pass123", is_active=True)

        self.tenant = Tenant.objects.create(name="Tenant Branches", slug="tenant-branches")
        self.store = Store.objects.create(tenant=self.tenant, name="Main Store")
        self.branch_a = Branch.objects.create(store=self.store, name="Branch A", address="Old address")
        self.branch_b = Branch.objects.create(store=self.store, name="Branch B")

        TenantMember.objects.create(tenant=self.tenant, user=self.owner, role="owner")
        TenantMember.objects.create(tenant=self.tenant, user=self.staff, role="staff")
        TenantMember.objects.create(tenant=self.tenant, user=self.employee, role="staff")
        BranchMember.objects.create(branch=self.branch_a, user=self.staff, role="staff")

    def _set_context(self, user, branch):
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = self.tenant.id
        session["active_store_id"] = self.store.id
        session["active_branch_id"] = branch.id
        session.save()

    def test_owner_can_access_branch_management_page(self):
        self._set_context(self.owner, self.branch_a)

        response = self.client.get(reverse("branch-management"), {"branch_id": self.branch_a.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_branch"], self.branch_a)
        self.assertContains(response, "Branch Management")

    def test_staff_cannot_access_branch_management_page(self):
        self._set_context(self.staff, self.branch_a)

        response = self.client.get(reverse("branch-management"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("home"))

    def test_owner_can_update_branch_details(self):
        self._set_context(self.owner, self.branch_a)

        response = self.client.post(
            reverse("branch-management") + f"?branch_id={self.branch_a.id}",
            data={
                "action": "update_branch",
                "branch-name": "Branch A Updated",
                "branch-code": "A-01",
                "branch-address": "New address",
                "branch-contact_phone": "+93-700-000001",
                "branch-contact_email": "branch-a@example.com",
                "branch-is_active": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.branch_a.refresh_from_db()
        self.assertEqual(self.branch_a.name, "Branch A Updated")
        self.assertEqual(self.branch_a.address, "New address")
        self.assertEqual(self.branch_a.contact_phone, "+93-700-000001")
        self.assertEqual(self.branch_a.contact_email, "branch-a@example.com")

    def test_owner_can_assign_employee_to_branch(self):
        self._set_context(self.owner, self.branch_b)

        response = self.client.post(
            reverse("branch-management") + f"?branch_id={self.branch_b.id}",
            data={
                "action": "add_employee",
                "employee-user": self.employee.id,
                "employee-role": "manager",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(BranchMember.objects.filter(branch=self.branch_b, user=self.employee, role="manager").exists())
        self.assertTrue(StoreMember.objects.filter(store=self.store, user=self.employee).exists())
