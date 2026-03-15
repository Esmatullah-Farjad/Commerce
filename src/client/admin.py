from django.contrib import admin

from .models import Branch, BranchMember, Store, StoreMember, Tenant, TenantMember, UserOnboarding

admin.site.register(Tenant)
admin.site.register(TenantMember)
admin.site.register(Store)
admin.site.register(StoreMember)
admin.site.register(Branch)
admin.site.register(BranchMember)
admin.site.register(UserOnboarding)
