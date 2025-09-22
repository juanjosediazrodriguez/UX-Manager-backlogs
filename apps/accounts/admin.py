from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "display_name", "role", "is_employee_verified")
    list_filter = ("role", "is_employee_verified")
    search_fields = ("email", "display_name", "username")

