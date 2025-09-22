from __future__ import annotations

from django.conf import settings
from django.db import models


class CompanyComment(models.Model):
    RATING_CHOICES = [(i, f"{i} estrella{'s' if i != 1 else ''}") for i in range(1, 6)]

    company_slug = models.SlugField(max_length=150, db_index=True)
    company_name = models.CharField(max_length=255)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_comments",
    )
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Comentario de empresa"
        verbose_name_plural = "Comentarios de empresas"

    def __str__(self) -> str:
        author = self.user.get_full_name() or self.user.email or self.user.username
        return f"{self.company_name} - {author} ({self.rating})"
