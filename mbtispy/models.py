"""Database models for optional MBTI Spy persistence."""

from django.db import models


class PlayerMBTIRecord(models.Model):
    """Stores player MBTI information when consent is granted."""

    session_code = models.CharField(max_length=16, db_index=True)
    player_name = models.CharField(max_length=128)
    department = models.CharField(max_length=128, blank=True)
    mbti = models.CharField(max_length=4)
    consent = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session_code", "player_name"]),
        ]
        verbose_name = "Player MBTI Record"
        verbose_name_plural = "Player MBTI Records"

    def __str__(self) -> str:
        return f"{self.player_name} ({self.mbti})"

