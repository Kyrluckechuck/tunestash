"""Django admin registration for Queuetip models the operator manages."""

from django.contrib import admin

from .models import QueuetipSignupAllowlist


@admin.register(QueuetipSignupAllowlist)
class QueuetipSignupAllowlistAdmin(admin.ModelAdmin):
    list_display = ("email", "added_at", "note")
    search_fields = ("email", "note")
    ordering = ("-added_at",)
