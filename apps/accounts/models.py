from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CANDIDATE = "CANDIDATE", "Candidato"
        EMPLOYEE = "EMPLOYEE", "Empleado"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CANDIDATE)
    display_name = models.CharField(max_length=150)
    area = models.CharField(max_length=150, blank=True)
    is_employee_verified = models.BooleanField(default=False)

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return self.display_name or self.username or self.email or str(self.pk)

