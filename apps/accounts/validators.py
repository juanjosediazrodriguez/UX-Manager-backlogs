from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext as _


@deconstructible
class UppercaseAndNumberValidator:
    message = _("La contraseña debe contener al menos una mayúscula y un número.")
    code = "password_no_upper_or_digit"

    def validate(self, password: str, user: Any | None = None) -> None:  # Django API
        if not re.search(r"[A-Z]", password) or not re.search(r"\d", password):
            raise ValidationError(self.message, code=self.code)

    def get_help_text(self) -> str:  # pragma: no cover - UI help text
        return self.message
