from __future__ import annotations

import random
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F

from .models import Prize


class PrizeUnavailableError(Exception):
    """Raised when no prize can be drawn from stock."""


@dataclass(slots=True)
class DrawResult:
    prize: Prize


def draw_prize() -> DrawResult:
    """Randomly select a prize and decrement its stock atomically."""

    with transaction.atomic():
        candidates = (
            Prize.objects.select_for_update()
            .filter(stock__gt=0)
            .order_by("id")
        )
        count = candidates.count()
        if count == 0:
            raise PrizeUnavailableError("No prize with remaining stock is available.")

        index = random.randint(0, count - 1)
        prize = candidates[index]

        Prize.objects.filter(id=prize.id).update(stock=F("stock") - 1)
        prize.refresh_from_db(fields=["stock"])
        return DrawResult(prize=prize)
