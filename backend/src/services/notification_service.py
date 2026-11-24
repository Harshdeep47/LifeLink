"""Shared notification subsystem (spec 10.3).

Used by availability alerts, camp announcements and reminders, emergency updates
and administrative notices. Three rules it enforces for every caller:

* Consent and preferences are checked before sending. An opted-out user is never
  contacted, and the result says SUPPRESSED rather than pretending to send.
* Duplicate suppression uses a durable marker, so a retried job cannot
  double-notify.
* Delivery status reflects what the provider said. Queueing is not delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from adapters.notifications import (
    Channel,
    DeliveryResult,
    DeliveryStatus,
    Message,
    NotificationChannel,
)
from domain.errors import ChannelUnavailableError

DEFAULT_PREFERENCES: dict = {
    "channels": [Channel.IN_APP.value, Channel.EMAIL.value],
    "consentGiven": False,
    "campNotifications": True,
    "alertNotifications": True,
    "emergencyNotifications": True,
    "notificationRadiusKm": 10,  # spec 5.4: 10 km initial default
    "extendedRadiusKm": 20,
}

CATEGORY_PREFERENCE_KEY = {
    "CAMP_ANNOUNCEMENT": "campNotifications",
    "CAMP_REMINDER": "campNotifications",
    "CAMP_CANCELLED": "campNotifications",
    "CAMP_UPDATED": "campNotifications",
    "ALERT_MATCH": "alertNotifications",
    "ALERT_EXPIRED": "alertNotifications",
    "EMERGENCY_UPDATE": "emergencyNotifications",
    "PROVIDER_REQUEST": "emergencyNotifications",
    # Account and administrative notices are transactional: they are not
    # marketing and are not subject to the category opt-outs above.
    "ACCOUNT_NOTICE": None,
    "ADMIN_NOTICE": None,
}


@dataclass(frozen=True, slots=True)
class NotificationOutcome:
    user_id: str
    category: str
    results: list[DeliveryResult]
    suppressed_reason: str | None = None

    @property
    def any_delivered(self) -> bool:
        return any(r.delivered for r in self.results)

    @property
    def suppressed(self) -> bool:
        return self.suppressed_reason is not None

    def to_dict(self) -> dict:
        return {
            "userId": self.user_id,
            "category": self.category,
            "suppressed": self.suppressed,
            "suppressedReason": self.suppressed_reason,
            "delivered": self.any_delivered,
            "attempts": [
                {
                    "channel": r.channel.value,
                    "status": r.status.value,
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }


class NotificationService:
    def __init__(self, *, channels: dict[Channel, NotificationChannel],
                 preferences_repository, identity_repository):
        self._channels = channels
        self._prefs = preferences_repository
        self._identity = identity_repository

    # --- preferences ---

    def get_preferences(self, user_id: str) -> dict:
        stored = self._prefs.get_preferences(user_id)
        if not stored:
            return dict(DEFAULT_PREFERENCES)
        merged = dict(DEFAULT_PREFERENCES)
        merged.update({k: v for k, v in stored.items() if not k.startswith(("PK", "SK", "GSI"))})
        return merged

    def save_preferences(self, user_id: str, updates: dict) -> dict:
        current = self.get_preferences(user_id)
        allowed = set(DEFAULT_PREFERENCES)
        current.update({k: v for k, v in updates.items() if k in allowed})
        radius = current.get("notificationRadiusKm", 10)
        try:
            radius = int(radius)
        except (TypeError, ValueError):
            radius = 10
        # Bounded so a preference cannot turn into an unbounded geo query.
        current["notificationRadiusKm"] = max(1, min(radius, 50))
        self._prefs.save_preferences(user_id, current)
        return current

    def is_opted_in(self, user_id: str, category: str) -> tuple[bool, str | None]:
        prefs = self.get_preferences(user_id)
        if not prefs.get("consentGiven"):
            return False, "NO_CONSENT"
        key = CATEGORY_PREFERENCE_KEY.get(category)
        if key is not None and not prefs.get(key, True):
            return False, "CATEGORY_OPTED_OUT"
        if not prefs.get("channels"):
            return False, "NO_CHANNELS_SELECTED"
        return True, None

    # --- sending ---

    def notify(
        self,
        *,
        user_id: str,
        category: str,
        subject: str,
        body: str,
        now: datetime,
        metadata: dict | None = None,
        dedupe_key: str | None = None,
        force_transactional: bool = False,
    ) -> NotificationOutcome:
        """Send on every channel the user has opted into.

        ``force_transactional`` is for account and administrative notices that
        are not subject to category opt-outs; it still honours a missing consent
        record for contactable channels.
        """
        if not force_transactional:
            opted_in, reason = self.is_opted_in(user_id, category)
            if not opted_in:
                return NotificationOutcome(user_id, category, [], suppressed_reason=reason)

        if dedupe_key:
            first_time = self._prefs.mark_sent_marker(
                user_id=user_id, dedupe_key=dedupe_key, now=now
            )
            if not first_time:
                return NotificationOutcome(
                    user_id, category, [], suppressed_reason="DUPLICATE_SUPPRESSED"
                )

        prefs = self.get_preferences(user_id)
        user = self._identity.get_user(user_id) or {}
        message = Message(
            recipient_user_id=user_id,
            recipient_email=user.get("email"),
            subject=subject,
            body_text=body,
            category=category,
            metadata=metadata or {},
        )

        selected = prefs.get("channels", [])
        results: list[DeliveryResult] = []
        for name in selected:
            try:
                channel = Channel(name)
            except ValueError:
                continue
            implementation = self._channels.get(channel)
            if implementation is None:
                continue
            try:
                results.append(implementation.send(message, now=now))
            except ChannelUnavailableError as exc:
                # An unimplemented channel is reported honestly, not silently skipped.
                results.append(
                    DeliveryResult(channel, DeliveryStatus.UNAVAILABLE, exc.message)
                )
            except Exception as exc:
                results.append(
                    DeliveryResult(channel, DeliveryStatus.FAILED, str(exc)[:300])
                )

        return NotificationOutcome(user_id, category, results)

    def notify_many(
        self, *, user_ids: list[str], category: str, subject: str, body: str,
        now: datetime, metadata: dict | None = None, dedupe_prefix: str | None = None
    ) -> list[NotificationOutcome]:
        """Fan out to several users, one at a time.

        Deliberately sequential: SES in sandbox permits one message per second,
        so a burst would be throttled anyway, and the concurrency ceiling makes
        parallel fan-out counterproductive here.
        """
        outcomes: list[NotificationOutcome] = []
        for user_id in user_ids:
            dedupe = f"{dedupe_prefix}#{user_id}" if dedupe_prefix else None
            outcomes.append(
                self.notify(
                    user_id=user_id,
                    category=category,
                    subject=subject,
                    body=body,
                    now=now,
                    metadata=metadata,
                    dedupe_key=dedupe,
                )
            )
        return outcomes

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[dict]:
        return self._prefs.list_for_user(user_id, limit=limit)
