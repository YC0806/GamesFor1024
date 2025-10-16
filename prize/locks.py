from __future__ import annotations

from contextlib import contextmanager

from django.db import connection
from django.db.utils import OperationalError


class PrizeLockError(Exception):
    """Raised when the draw lock cannot be acquired or released."""


_LOCK_NAME = "prize:draw"


@contextmanager
def prize_draw_lock(timeout: int = 5):
    """Acquire a MySQL named lock to serialize draw operations."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, %s)", [_LOCK_NAME, timeout])
            row = cursor.fetchone()
    except OperationalError as exc:
        raise PrizeLockError(f"Failed to acquire draw lock: {exc}") from exc

    if not row or row[0] != 1:
        raise PrizeLockError("Draw system is busy. Please try again later.")

    try:
        yield
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT RELEASE_LOCK(%s)", [_LOCK_NAME])
        except OperationalError:
            # Lock will eventually timeout server-side; nothing else we can do.
            pass

