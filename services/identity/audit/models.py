from django.db import models

# Create your models here.
import uuid

from django.db import models


class ActivityLog(models.Model):
    """Records important actions performed in the forum."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    actor_id = models.UUIDField()
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    target_id = models.UUIDField()
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "activity_logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} ({self.created_at})"


class Outbox(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "outbox"
        ordering = ["created_at", "id"]


class ProcessedEvent(models.Model):
    event_id = models.UUIDField()
    consumer = models.CharField(max_length=100)

    class Meta:
        db_table = "processed_events"
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "consumer"],
                name="unique_processed_event_consumer",
            )
        ]

    def __str__(self):
        return f"{self.event_id} ({self.consumer})"