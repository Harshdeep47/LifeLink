"""Shared test fixtures.

Every test that touches time passes an explicit instant. Nothing in the domain
layer reads the system clock, so these tests are deterministic by construction
rather than by patching.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.blood import BatchStatus, BloodGroup, Component
from domain.inventory import Batch

# A fixed reference instant used throughout the suite.
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


def hours_ago(h: float, base: datetime = NOW) -> datetime:
    return base - timedelta(hours=h)


def hours_ahead(h: float, base: datetime = NOW) -> datetime:
    return base + timedelta(hours=h)


def days_ago(d: float, base: datetime = NOW) -> datetime:
    return base - timedelta(days=d)


def days_ahead(d: float, base: datetime = NOW) -> datetime:
    return base + timedelta(days=d)


@pytest.fixture
def now() -> datetime:
    return NOW


def make_batch(
    *,
    batch_id: str = "batch-1",
    facility_id: str = "fac-1",
    organization_id: str = "org-1",
    blood_group: BloodGroup = BloodGroup.O_NEG,
    component: Component = Component.PRBC,
    available_units: int = 10,
    status: BatchStatus = BatchStatus.AVAILABLE,
    collected_at: datetime | None = None,
    expires_at: datetime | None = None,
    last_updated_at: datetime | None = None,
    last_verified_at: datetime | None = None,
    update_source: str = "MANUAL",
    version: int = 1,
    quarantine_reason: str | None = None,
) -> Batch:
    return Batch(
        batch_id=batch_id,
        facility_id=facility_id,
        organization_id=organization_id,
        blood_group=blood_group,
        component=component,
        available_units=available_units,
        status=status,
        collected_at=collected_at if collected_at is not None else days_ago(10),
        expires_at=expires_at if expires_at is not None else days_ahead(20),
        last_updated_at=last_updated_at if last_updated_at is not None else hours_ago(1),
        last_verified_at=last_verified_at,
        update_source=update_source,
        version=version,
        quarantine_reason=quarantine_reason,
    )


@pytest.fixture
def batch_factory():
    return make_batch
