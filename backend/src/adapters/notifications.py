"""Notification channels (spec 10.3, ADR-0015).

Three honesty rules are built into the types here:

* A queue write is not a delivery. ``DeliveryResult`` records what the provider
  actually said, and ``QUEUED`` is a distinct state from ``SENT``.
* SMS is NOT implemented on this account -- the SCP denies it and the service is
  Paid-Plan only. Asking for it returns CHANNEL_UNAVAILABLE rather than silently
  succeeding or pretending to send.
* Local development writes to a directory on disk instead of faking provider
  responses, so a developer can see exactly what would have been sent.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from domain.clock import to_iso
from domain.errors import ChannelUnavailableError


class Channel(StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SMS = "SMS"  # declared so preferences can reference it; not implemented


class DeliveryStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class Message:
    recipient_user_id: str
    subject: str
    body_text: str
    category: str
    body_html: str | None = None
    recipient_email: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    channel: Channel
    status: DeliveryStatus
    detail: str | None = None
    provider_message_id: str | None = None

    @property
    def delivered(self) -> bool:
        """True only when the provider accepted it. QUEUED is not delivered."""
        return self.status == DeliveryStatus.SENT


class NotificationChannel(Protocol):
    channel: Channel

    def send(self, message: Message, *, now: datetime) -> DeliveryResult:
        ...


class SesEmailChannel:
    """Email via Amazon SES.

    The account is in the SES sandbox (verified recipients only, 200/day, 1/sec),
    which is recorded as a known limitation rather than worked around.
    """

    channel = Channel.EMAIL

    def __init__(self, sender: str, client=None, configuration_set: str | None = None):
        self._sender = sender
        self._client = client
        self._configuration_set = configuration_set

    def _ses(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "sesv2", region_name=os.environ.get("AWS_REGION", "ap-southeast-2")
            )
        return self._client

    def send(self, message: Message, *, now: datetime) -> DeliveryResult:
        if not message.recipient_email:
            return DeliveryResult(
                self.channel, DeliveryStatus.FAILED, "recipient has no email address"
            )

        body: dict = {"Text": {"Data": message.body_text, "Charset": "UTF-8"}}
        if message.body_html:
            body["Html"] = {"Data": message.body_html, "Charset": "UTF-8"}

        request = {
            "FromEmailAddress": self._sender,
            "Destination": {"ToAddresses": [message.recipient_email]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": body,
                }
            },
        }
        if self._configuration_set:
            request["ConfigurationSetName"] = self._configuration_set

        try:
            response = self._ses().send_email(**request)
        except Exception as exc:  # provider failure is data, not a crash
            return DeliveryResult(self.channel, DeliveryStatus.FAILED, str(exc)[:300])

        return DeliveryResult(
            self.channel,
            DeliveryStatus.SENT,
            detail="accepted by SES",
            provider_message_id=response.get("MessageId"),
        )


class InAppChannel:
    """In-app notifications, stored for the user to read in the dashboard."""

    channel = Channel.IN_APP

    def __init__(self, notification_repository):
        self._repo = notification_repository

    def send(self, message: Message, *, now: datetime) -> DeliveryResult:
        try:
            record = self._repo.record_notification(
                {
                    "userId": message.recipient_user_id,
                    "subject": message.subject,
                    "body": message.body_text,
                    "category": message.category,
                    "channel": Channel.IN_APP.value,
                    "deliveryStatus": DeliveryStatus.SENT.value,
                    "read": False,
                    "metadata": message.metadata,
                },
                now=now,
            )
        except Exception as exc:
            return DeliveryResult(self.channel, DeliveryStatus.FAILED, str(exc)[:300])
        return DeliveryResult(
            self.channel,
            DeliveryStatus.SENT,
            detail="stored for in-app delivery",
            provider_message_id=record.get("notificationId"),
        )


class UnavailableSmsChannel:
    """SMS is deliberately not implemented (ADR-0015).

    This class exists so that requesting SMS produces a clear, honest refusal
    instead of a silent no-op that would look like success in the audit trail.
    """

    channel = Channel.SMS

    def send(self, message: Message, *, now: datetime) -> DeliveryResult:
        raise ChannelUnavailableError(
            "SMS delivery is not available for this deployment",
            details={
                "reason": "AWS End User Messaging SMS is a Paid-Plan service and is "
                "denied by the account's service control policy.",
                "implemented": False,
                "alternatives": [Channel.EMAIL.value, Channel.IN_APP.value],
            },
        )


class LocalFileChannel:
    """Local-development channel (ADR-0011).

    Writes what would have been sent to ``.local-outbox/`` so it can be inspected.
    Reports SENT because the local write genuinely succeeded; the file itself
    makes clear no real message left the machine.
    """

    def __init__(self, channel: Channel, directory: str | Path = ".local-outbox"):
        self.channel = channel
        self._dir = Path(directory)

    def send(self, message: Message, *, now: datetime) -> DeliveryResult:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            message_id = str(uuid.uuid4())
            path = self._dir / f"{now.strftime('%Y%m%dT%H%M%S')}-{self.channel.value}-{message_id[:8]}.json"
            path.write_text(
                json.dumps(
                    {
                        "channel": self.channel.value,
                        "sentAt": to_iso(now),
                        "recipientUserId": message.recipient_user_id,
                        "recipientEmail": message.recipient_email,
                        "subject": message.subject,
                        "body": message.body_text,
                        "category": message.category,
                        "metadata": message.metadata,
                        "note": "LOCAL DEVELOPMENT -- no message was actually sent.",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            return DeliveryResult(self.channel, DeliveryStatus.FAILED, str(exc)[:300])
        return DeliveryResult(
            self.channel,
            DeliveryStatus.SENT,
            detail=f"written to {path.name} (local mode)",
            provider_message_id=message_id,
        )


def build_channels(*, local_mode: bool, notification_repository=None,
                   sender_email: str | None = None) -> dict[Channel, NotificationChannel]:
    """Wire the channel set for the current environment."""
    if local_mode:
        return {
            Channel.EMAIL: LocalFileChannel(Channel.EMAIL),
            Channel.IN_APP: (
                InAppChannel(notification_repository)
                if notification_repository is not None
                else LocalFileChannel(Channel.IN_APP)
            ),
            Channel.SMS: UnavailableSmsChannel(),
        }
    return {
        Channel.EMAIL: SesEmailChannel(sender_email or os.environ.get("SES_SENDER", "")),
        Channel.IN_APP: InAppChannel(notification_repository),
        Channel.SMS: UnavailableSmsChannel(),
    }
