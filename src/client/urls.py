from django.urls import path

from . import views

urlpatterns = [
    path("", views.root_view, name="root-view"),
    path("landing/", views.landing, name="landing"),
    path("language/switch/<str:lang_code>", views.switch_language, name="switch-language"),
    path("auth/sign-in", views.signin, name="sign-in"),
    path("auth/sign-up", views.signup, name="sign-up"),
    path("auth/sign-out", views.signout, name="sign-out"),
    path("tenancy/select-tenant", views.select_tenant, name="select-tenant"),
    path("tenancy/select-branch", views.select_branch, name="select-branch"),
    path("tenancy/switch-context", views.switch_context, name="switch-context"),
    path("tenancy/branches", views.branch_management, name="branch-management"),
    path("tenancy/pending-users", views.pending_users, name="pending-users"),
    path(
        "tenancy/pending-users/<int:onboarding_id>/activate",
        views.activate_user,
        name="activate-user",
    ),
]
