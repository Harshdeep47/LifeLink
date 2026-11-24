"""Seeding twice must not duplicate synthetic request events.

The defect this guards (KNOWN_LIMITATIONS 1.19). The seeder wrote request
events with the sort key ``EVENT#<iso-now>#seed0001``. The suffix was fixed but
the timestamp came from the run clock, so every seed run produced a *new* sort
key for the same logical event rather than overwriting the old one. Five runs
against the deployed stack left ``demo-req-p1-1`` carrying five
``REQUEST_CREATED`` events, and the emergency tracking page rendered all five.

`seed_cloud.py` promises in its own docstring that "a second run rewrites the
same items rather than adding more". That held for every record type except
this one, and nothing tested it.

These tests run the real seeding function against moto, twice, and compare.

The last class is as important as the rest: the *application's* event writer
must keep appending. Real history is append-only, and a fix that made genuine
events overwrite each other would be far worse than the duplication it
replaced.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SEED_SCRIPT = ROOT / "scripts" / "seed_demo.py"


def _load_seed_demo():
    """Import the seeder, then undo its module-level endpoint side effect.

    Importing it runs ``os.environ.setdefault("DYNAMODB_ENDPOINT",
    "http://localhost:8000")``. Left in place, every repository would be built
    against localhost instead of moto and the test would silently exercise
    nothing. This is the same trap that once made a cloud seed run write to the
    local database while reporting success, which is why the cloud seeder now
    inspects its real boto3 client rather than the environment variable.
    """
    spec = importlib.util.spec_from_file_location("seed_demo_under_test", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    os.environ.pop("DYNAMODB_ENDPOINT", None)
    from repositories.dynamo import reset_resource_cache

    reset_resource_cache()
    return module


@pytest.fixture
def seeder_factory(aws):
    """Builds a DemoSeeder bound to the mocked tables.

    A factory rather than a single instance, because each simulated "run"
    needs its own seeder with its own clock -- which is exactly the condition
    that exposed the defect.
    """
    seed_demo = _load_seed_demo()

    def build(now: datetime):
        return seed_demo.DemoSeeder(now)

    build.module = seed_demo
    return build


def event_rows(prefix: str = "lifelink-test") -> list[dict]:
    """Every REQUEST_EVENT row in the emergency table."""
    import boto3

    client = boto3.client("dynamodb", region_name="ap-southeast-2")
    rows: list[dict] = []
    kwargs = {"TableName": f"{prefix}-emergency"}
    while True:
        page = client.scan(**kwargs)
        rows.extend(
            i for i in page["Items"]
            if i.get("entityType", {}).get("S") == "REQUEST_EVENT"
        )
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return rows


def keys_of(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["PK"]["S"], r["SK"]["S"]) for r in rows}


FIRST_RUN = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
# Nine days later, which is what made the live duplication visible.
SECOND_RUN = FIRST_RUN + timedelta(days=9, hours=3, minutes=17)


class TestSeedingTwiceDoesNotDuplicateEvents:
    def test_one_run_writes_one_event_per_request(self, seeder_factory):
        seeder_factory(FIRST_RUN).seed_emergency()
        rows = event_rows()

        assert rows, "the seeder wrote no request events at all"
        per_request: dict[str, int] = {}
        for r in rows:
            per_request[r["PK"]["S"]] = per_request.get(r["PK"]["S"], 0) + 1
        assert set(per_request.values()) == {1}, per_request

    def test_a_second_run_does_not_increase_the_event_count(self, seeder_factory):
        seeder_factory(FIRST_RUN).seed_emergency()
        first = event_rows()
        assert first

        seeder_factory(SECOND_RUN).seed_emergency()
        second = event_rows()

        assert len(second) == len(first), (
            f"second run added {len(second) - len(first)} event row(s); "
            "the sort key is not deterministic"
        )

    def test_a_second_run_writes_the_same_sort_keys(self, seeder_factory):
        seeder_factory(FIRST_RUN).seed_emergency()
        before = keys_of(event_rows())

        seeder_factory(SECOND_RUN).seed_emergency()
        after = keys_of(event_rows())

        assert after == before

    def test_three_runs_still_leave_one_event_per_request(self, seeder_factory):
        """Five runs is what produced the live defect, so prove it repeats."""
        for offset in (0, 9, 18):
            seeder_factory(FIRST_RUN + timedelta(days=offset)).seed_emergency()

        rows = event_rows()
        per_request: dict[str, int] = {}
        for r in rows:
            per_request[r["PK"]["S"]] = per_request.get(r["PK"]["S"], 0) + 1
        assert set(per_request.values()) == {1}, per_request

    def test_no_request_has_two_created_events(self, seeder_factory):
        """The exact symptom: a timeline showing REQUEST_CREATED repeatedly."""
        for offset in (0, 9):
            seeder_factory(FIRST_RUN + timedelta(days=offset)).seed_emergency()

        created: dict[str, int] = {}
        for r in event_rows():
            if r.get("eventType", {}).get("S") == "REQUEST_CREATED":
                created[r["PK"]["S"]] = created.get(r["PK"]["S"], 0) + 1
        assert created, "no REQUEST_CREATED events were written"
        assert set(created.values()) == {1}, created

    def test_the_second_run_still_refreshes_the_displayed_timestamp(self, seeder_factory):
        """Overwriting must not freeze `occurredAt`.

        The key is deterministic; the timestamp the interface shows is not, and
        must keep moving with the run clock or the refresh would be pointless.
        """
        seeder_factory(FIRST_RUN).seed_emergency()
        before = {r["SK"]["S"]: r["occurredAt"]["S"] for r in event_rows()}

        seeder_factory(SECOND_RUN).seed_emergency()
        after = {r["SK"]["S"]: r["occurredAt"]["S"] for r in event_rows()}

        assert set(after) == set(before)
        assert any(after[k] != before[k] for k in before), (
            "occurredAt did not change, so re-seeding would not refresh the timeline"
        )


class TestTheSortKeyItself:
    def test_it_is_deterministic(self, seeder_factory):
        sk = seeder_factory.module.seed_event_sk
        assert sk(0) == sk(0)

    def test_it_carries_no_timestamp(self, seeder_factory):
        """No date in the key is the whole point -- that is what varied."""
        import re

        sk = seeder_factory.module.seed_event_sk(0)
        # Deliberately not `"T" not in sk`: the literal prefix "EVENT" ends in
        # a T, which made an earlier version of this assertion fail for a
        # reason that had nothing to do with the property being tested.
        assert not re.search(r"\d{4}-\d{2}-\d{2}", sk), sk
        assert not sk.endswith("Z"), sk

    def test_distinct_ordinals_give_distinct_ordered_keys(self, seeder_factory):
        sk = seeder_factory.module.seed_event_sk
        keys = [sk(i) for i in range(4)]
        assert len(set(keys)) == 4
        assert keys == sorted(keys)

    @pytest.mark.parametrize(
        "genuine",
        [
            "EVENT#2026-11-24T08:21:12.722292Z#a1b2c3d4",
            "EVENT#1999-01-01T00:00:00.000000Z#deadbeef",
            "EVENT#2999-12-31T23:59:59.999999Z#ffffffff",
        ],
    )
    def test_a_seeded_event_sorts_before_any_genuine_one(self, seeder_factory, genuine):
        """Ordering is lexicographic on the whole sort key.

        `load_full_request` sorts by SK, so this is what keeps a request's
        seeded creation event at the head of its timeline rather than after
        events the application appended later.
        """
        seeded = seeder_factory.module.seed_event_sk(0)
        assert sorted([genuine, seeded]) == [seeded, genuine]


class TestGenuineEventsStillAppend:
    """The application's own writer must stay append-only.

    Making real events idempotent would be a far worse defect than the
    duplication this change removes: a request's history would silently lose
    entries.
    """

    def test_two_application_events_produce_two_rows(self, aws):
        from repositories.emergency_repo import EmergencyRepository

        repo = EmergencyRepository()
        repo.create_request(
            {
                "requestId": "req-append-1",
                "bloodGroup": "O-",
                "component": "PRBC",
                "unitsRequired": 2,
                "requestingOrganizationId": "org-hosp-patiala-1",
            },
            now=FIRST_RUN,
        )
        repo.append_event(
            request_id="req-append-1",
            event_type="TRANSITION_ONE",
            actor_id="user-1",
            now=FIRST_RUN + timedelta(minutes=1),
        )
        repo.append_event(
            request_id="req-append-1",
            event_type="TRANSITION_TWO",
            actor_id="user-1",
            now=FIRST_RUN + timedelta(minutes=2),
        )

        # `create_request` writes its own creation event, so filter to the two
        # this test appended rather than asserting a total.
        mine = [
            r for r in event_rows()
            if r["PK"]["S"] == "REQUEST#req-append-1"
            and r["eventType"]["S"].startswith("TRANSITION_")
        ]
        types = sorted(r["eventType"]["S"] for r in mine)
        assert types == ["TRANSITION_ONE", "TRANSITION_TWO"], types

    def test_two_events_at_the_same_instant_both_survive(self, aws):
        """Same timestamp, different uuid suffix: both must be kept."""
        from repositories.emergency_repo import EmergencyRepository

        repo = EmergencyRepository()
        repo.create_request(
            {
                "requestId": "req-append-2",
                "bloodGroup": "A+",
                "component": "PRBC",
                "unitsRequired": 1,
                "requestingOrganizationId": "org-hosp-patiala-1",
            },
            now=FIRST_RUN,
        )
        for _ in range(2):
            repo.append_event(
                request_id="req-append-2",
                event_type="SAME_INSTANT",
                actor_id="user-1",
                now=FIRST_RUN,
            )

        mine = [
            r for r in event_rows()
            if r["PK"]["S"] == "REQUEST#req-append-2"
            and r["eventType"]["S"] == "SAME_INSTANT"
        ]
        assert len(mine) == 2, [r["SK"]["S"] for r in mine]
        # Same instant, different uuid suffix: the suffix is what keeps them
        # distinct, and it is why the application writer must not be made
        # deterministic the way the seeder's was.
        assert len({r["SK"]["S"] for r in mine}) == 2

class TestTheTimelineTheApiReturns:
    """Requirement 7, at the layer the page actually reads.

    `RequestTrackingPage` renders `request.timeline`, which the API builds from
    `emergency_repo.load_full_request` -- the same function called here. So a
    single REQUEST_CREATED entry after repeated seeding is the data-level
    proof that the page stops repeating it.
    """

    def test_the_timeline_has_one_created_entry_after_repeated_seeding(self, seeder_factory):
        from repositories.emergency_repo import EmergencyRepository

        for offset in (0, 9, 18, 27):
            seeder_factory(FIRST_RUN + timedelta(days=offset)).seed_emergency()

        full = EmergencyRepository().load_full_request("demo-req-p1-1")
        assert full is not None
        created = [
            e for e in full["events"]
            if e.get("eventType") == "REQUEST_CREATED"
        ]
        assert len(created) == 1, [e["SK"] for e in full["events"]]

    def test_the_seeded_creation_event_is_first_in_the_timeline(self, seeder_factory):
        """Ordering is by sort key, so prove the deterministic key stays first
        even once the application has appended a genuine event afterwards."""
        from repositories.emergency_repo import EmergencyRepository

        seeder_factory(FIRST_RUN).seed_emergency()
        repo = EmergencyRepository()
        repo.append_event(
            request_id="demo-req-p1-1",
            event_type="TRANSITION_EXPIRED",
            actor_id="system",
            now=FIRST_RUN + timedelta(days=1),
        )

        events = EmergencyRepository().load_full_request("demo-req-p1-1")["events"]
        assert [e.get("eventType") for e in events] == [
            "REQUEST_CREATED",
            "TRANSITION_EXPIRED",
        ], [e["SK"] for e in events]

    def test_a_genuine_event_survives_repeated_seeding(self, seeder_factory):
        """Re-seeding must never remove real history."""
        from repositories.emergency_repo import EmergencyRepository

        seeder_factory(FIRST_RUN).seed_emergency()
        EmergencyRepository().append_event(
            request_id="demo-req-p1-1",
            event_type="TRANSITION_EXPIRED",
            actor_id="system",
            now=FIRST_RUN + timedelta(days=1),
        )

        seeder_factory(SECOND_RUN).seed_emergency()

        events = EmergencyRepository().load_full_request("demo-req-p1-1")["events"]
        types = [e.get("eventType") for e in events]
        assert types.count("TRANSITION_EXPIRED") == 1, types
        assert types.count("REQUEST_CREATED") == 1, types
