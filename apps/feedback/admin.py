from django.contrib import admin

from .models import CompanyComment


@admin.register(CompanyComment)
class CompanyCommentAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "rating", "created_at")
    list_filter = ("rating", "company_slug", "created_at")
    search_fields = ("company_name", "company_slug", "user__email", "comment")
    autocomplete_fields = ("user",)
    date_hierarchy = "created_at"
