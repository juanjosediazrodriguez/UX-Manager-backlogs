from __future__ import annotations

from allauth.account.forms import SignupForm
from django import forms

from .models import User


class UXSignupForm(SignupForm):
    display_name = forms.CharField(label="Nombre", max_length=150)
    role = forms.ChoiceField(label="Rol", choices=User.Role.choices)

    def custom_signup(self, request, user):  # type: ignore[override]
        user.display_name = self.cleaned_data.get("display_name", "")
        user.role = self.cleaned_data.get("role", User.Role.CANDIDATE)
        user.save(update_fields=["display_name", "role"])
        return user

