"""The duplicate-event cleanup script's decision logic.

A delete tool is only as safe as the predicate that selects its targets, so
that predicate is tested directly and offline. No AWS, no network: these call
the functions the script uses to decide.

The tests are written from the question "what must this never delete?" rather
than "what should it delete?", because the second kind of mistake is
recoverable by re-seeding and the first is not.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "dedupe_request_events.py"


def _load():
    spec = importlib.util.spec_from_file_location("dedupe_request_events", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dedupe = _load()


def row(
    *,
    pk="REQUEST#demo-req-p1-1",
    sk="EVENT#2026-11-15T10:00:00Z#seed0001",
    entity="REQUEST_EVENT",
    demo=True,
    event_type="REQUEST_CREATED",
    occurred="2026-11-15T10:00:00Z",
):
    item = {
        "PK": {"S": pk},
        "SK": {"S": sk},
        "entityType": {"S": entity},
        "eventType": {"S": event_type},
        "occurredAt": {"S": occurred},
    }
    if demo is not None:
        item["demoData"] = {"BOOL": demo}
    return item


class TestWhatItMustNeverSelect:
    def test_a_genuine_application_event_is_never_a_candidate(self):
        """Written by append_event: uuid suffix, no seed marker."""
        genuine = row(sk="EVENT#2026-11-16T14:10:20.681118Z#c07d7f6f", demo=None)
        assert dedupe.is_candidate(genuine) is False

    def test_a_seed_shaped_key_on_a_non_demo_row_is_not_a_candidate(self):
        assert dedupe.is_candidate(row(demo=False)) is False
        assert dedupe.is_candidate(row(demo=None)) is False

    def test_a_request_record_is_never_a_candidate(self):
        assert dedupe.is_candidate(row(sk="META", entity="EMERGENCY_REQUEST")) is False

    def test_a_provider_response_is_never_a_candidate(self):
        assert (
            dedupe.is_candidate(
                row(sk="RESPONSE#org-bb-patiala-1", entity="PROVIDER_RESPONSE")
            )
            is False
        )

    def test_an_event_on_a_user_created_request_is_never_a_candidate(self):
        """A ULID request id, not the seeder's fixed prefix."""
        assert (
            dedupe.is_candidate(row(pk="REQUEST#01M7G1E44FG9KG1CT5EBB2ZG01"))
            is False
        )

    @pytest.mark.parametrize(
        "entity",
        ["AUDIT", "DONATION", "IMPACT_LEDGER", "NOTIFICATION", "RESERVATION", ""],
    )
    def test_no_other_entity_type_is_a_candidate(self, entity):
        assert dedupe.is_candidate(row(entity=entity)) is False

    def test_a_seed_suffix_without_the_event_prefix_is_not_a_candidate(self):
        assert dedupe.is_candidate(row(sk="AUDIT#2026-11-15T10:00:00Z#seed0001")) is False

    def test_a_missing_entity_type_is_not_a_candidate(self):
        bad = row()
        del bad["entityType"]
        assert dedupe.is_candidate(bad) is False


class TestWhatItSelects:
    def test_an_old_timestamped_seeded_event_is_a_candidate(self):
        assert dedupe.is_candidate(row()) is True

    def test_the_new_deterministic_key_is_also_a_candidate(self):
        """In scope, but it is the row that gets kept -- see choose_keeper."""
        assert dedupe.is_candidate(row(sk="EVENT#0000#seed0001")) is True


class TestWhichRowSurvives:
    def test_the_deterministic_key_wins_when_present(self):
        canonical = row(sk="EVENT#0000#seed0001", occurred="2026-11-24T05:00:00Z")
        older = row(sk="EVENT#2026-11-14T11:40:02Z#seed0001", occurred="2026-11-14T11:40:02Z")
        keeper = dedupe.choose_keeper([older, canonical])
        assert keeper["SK"]["S"] == "EVENT#0000#seed0001"

    def test_without_a_deterministic_key_the_earliest_survives(self):
        a = row(sk="EVENT#2026-11-15T13:00:00Z#seed0001", occurred="2026-11-15T13:00:00Z")
        b = row(sk="EVENT#2026-11-14T11:00:00Z#seed0001", occurred="2026-11-14T11:00:00Z")
        c = row(sk="EVENT#2026-11-24T05:00:00Z#seed0001", occurred="2026-11-24T05:00:00Z")
        keeper = dedupe.choose_keeper([a, b, c])
        assert keeper["occurredAt"]["S"] == "2026-11-14T11:00:00Z"

    def test_it_always_returns_one_of_the_rows_it_was_given(self):
        rows = [row(sk=f"EVENT#2026-11-1{i}T10:00:00Z#seed0001") for i in range(3)]
        assert dedupe.choose_keeper(rows) in rows

    def test_a_single_row_group_keeps_that_row(self):
        only = row()
        assert dedupe.choose_keeper([only]) is only

    def test_a_group_with_a_missing_occurredAt_does_not_crash(self):
        a = row()
        del a["occurredAt"]
        b = row(sk="EVENT#2026-11-20T10:00:00Z#seed0001", occurred="2026-11-20T10:00:00Z")
        assert dedupe.choose_keeper([a, b]) in (a, b)


class TestTheDeterministicKeyPattern:
    @pytest.mark.parametrize("sk", ["EVENT#0000#seed0001", "EVENT#0001#seed0001", "EVENT#9999#seed0001"])
    def test_it_matches_the_fixed_form(self, sk):
        assert dedupe.DETERMINISTIC_SK.match(sk)

    @pytest.mark.parametrize(
        "sk",
        [
            "EVENT#2026-11-15T10:00:00Z#seed0001",   # the old form
            "EVENT#0000#c07d7f6f",                   # genuine suffix
            "EVENT#000#seed0001",                    # too few digits
            "EVENT#00000#seed0001",                  # too many
            "EVENT#0000#seed0001x",                  # trailing junk
        ],
    )
    def test_it_rejects_everything_else(self, sk):
        assert not dedupe.DETERMINISTIC_SK.match(sk)


class TestGroupingNeverEmptiesATimeline:
    """Condition 5, expressed as a property over the grouping logic."""

    def test_every_group_retains_exactly_one_row(self):
        rows = [
            row(pk="REQUEST#demo-req-p1-1", sk=f"EVENT#2026-11-1{i}T10:00:00Z#seed0001",
                occurred=f"2026-11-1{i}T10:00:00Z")
            for i in range(1, 6)
        ] + [
            row(pk="REQUEST#demo-req-p2-1", sk="EVENT#2026-11-15T10:00:00Z#seed0001"),
        ]

        groups: dict[tuple[str, str], list[dict]] = {}
        for r in rows:
            assert dedupe.is_candidate(r)
            groups.setdefault((r["PK"]["S"], r["eventType"]["S"]), []).append(r)

        for group in groups.values():
            keeper = dedupe.choose_keeper(group)
            losers = [r for r in group if r["SK"]["S"] != keeper["SK"]["S"]]
            assert len(group) - len(losers) == 1, "exactly one row must survive"

    def test_distinct_event_types_are_grouped_separately(self):
        """Deleting across event types would erase real lifecycle history."""
        created = row(event_type="REQUEST_CREATED")
        certified = row(event_type="HOSPITAL_CERTIFIED",
                        sk="EVENT#2026-11-15T11:00:00Z#seed0001")
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in (created, certified):
            groups.setdefault((r["PK"]["S"], r["eventType"]["S"]), []).append(r)
        assert len(groups) == 2
        assert all(len(g) == 1 for g in groups.values())
