from __future__ import annotations

from django.db import models


class Prize(models.Model):
    """Represents a prize item with remaining stock."""

    name = models.CharField(max_length=255, unique=True)
    stock = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} (stock={self.stock})"

    def to_payload(self) -> dict[str, int | str]:
        return {
            "id": self.id,
            "name": self.name,
            "stock": self.stock,
        }
