"""Camp reminder indexing.

Regression suite for a real defect: camps created through the API were missing
the reminder-window index attribute, so the scheduled sweep never found them.
The reminder logic itself was correct and fully unit-tested; the camp simply
was not in the query's result set.

That failure mode is invisible -- no error, no alarm, just reminders that never
arrive -- so the index population is asserted directly rather than inferred
from the sweep appearing to work.
"""
from __future__ import annotations

import pytest
from boto3.dynamodb.conditions import Key

from domain.clock import to_iso
from tests.integration.conftest import hours_ahead, make_context

pytestmark = pytest.mark.integration


def create_camp(camp_service, now, *, name="Reminder Camp", starts_in_hours=26):
    organizer = make_context(
        user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
    )
    return camp_service.create_camp(
        context=organizer,
        name=name,
        description="reminder indexing",
        latitude=30.3398,
        longitude=76.3869,
        address="1 Test Road",
        city="Patiala",
        starts_at=hours_ahead(starts_in_hours),
        ends_at=hours_ahead(starts_in_hours + 8),
        capacity=20,
        now=now,
    )


class TestReminderIndexing:
    def test_a_camp_created_through_the_service_is_in_the_reminder_index(
        self, seeded, camp_service, repos, now
    ):
        camp = create_camp(camp_service, now)

        rows = repos.camps.query_all(
            key_condition=Key("GSI4PK").eq("REMINDER#WINDOW"),
            index_name="GSI4-reminder",
        )
        ids = {row.get("campId") for row in rows}
        assert camp["campId"] in ids, (
            "a camp created through the API must appear in the reminder index, "
            "or it will silently never produce reminders"
        )

    def test_the_index_sort_key_is_the_start_time(
        self, seeded, camp_service, repos, now
    ):
        camp = create_camp(camp_service, now, starts_in_hours=30)
        rows = repos.camps.query_all(
            key_condition=Key("GSI4PK").eq("REMINDER#WINDOW"),
            index_name="GSI4-reminder",
        )
        row = next(r for r in rows if r.get("campId") == camp["campId"])
        assert row["GSI4SK"] == to_iso(hours_ahead(30))

    def test_a_time_window_query_finds_only_camps_in_that_window(
        self, seeded, camp_service, repos, now
    ):
        soon = create_camp(camp_service, now, name="Soon", starts_in_hours=24)
        later = create_camp(camp_service, now, name="Later", starts_in_hours=100)

        rows = repos.camps.query_all(
            key_condition=Key("GSI4PK").eq("REMINDER#WINDOW")
            & Key("GSI4SK").between(
                to_iso(hours_ahead(23)), to_iso(hours_ahead(25))
            ),
            index_name="GSI4-reminder",
        )
        found = {row.get("campId") for row in rows}
        assert soon["campId"] in found
        assert later["campId"] not in found

    def test_the_sweep_can_see_a_service_created_camp(
        self, seeded, camp_service, now
    ):
        """End to end: the sweep's own helper must return the camp.

        This is the assertion that would have failed before the fix.
        """
        create_camp(camp_service, now, starts_in_hours=24)

        window = camp_service._upcoming_camps_between(
            hours_ahead(23), hours_ahead(25)
        )
        assert window, "the reminder sweep found no camps in a window containing one"


class TestReminderSweep:
    def test_the_sweep_sends_to_a_registered_consenting_donor(
        self, seeded, camp_service, notification_service, now
    ):
        from adapters.notifications import Channel

        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        donor = make_context(user_id="u-donor-1", roles=("DONOR",), organization_id=None)

        camp = create_camp(camp_service, now, starts_in_hours=24)
        camp_service.approve_camp(
            context=admin, camp_id=camp["campId"], approve=True, now=now
        )
        camp_service.register(context=donor, camp_id=camp["campId"], now=now)

        in_app = notification_service.test_channels[Channel.IN_APP]
        before = len(in_app.sent)

        outcome = camp_service.send_due_reminders(now=now)

        assert outcome["sent"] >= 1, f"expected a reminder to be sent, got {outcome}"
        assert len(in_app.sent) > before

    def test_a_cancelled_camp_produces_no_reminder(
        self, seeded, camp_service, now
    ):
        """The sweep re-checks camp status at send time, not at schedule time."""
        admin = make_context(user_id="u-admin", roles=("PLATFORM_ADMIN",), organization_id=None)
        organizer = make_context(
            user_id="u-camp-org", roles=("CAMP_ORGANIZER",), organization_id="org-camp-1"
        )
        donor = make_context(user_id="u-donor-2", roles=("DONOR",), organization_id=None)

        camp = create_camp(camp_service, now, name="Doomed", starts_in_hours=24)
        camp_service.approve_camp(
            context=admin, camp_id=camp["campId"], approve=True, now=now
        )
        camp_service.register(context=donor, camp_id=camp["campId"], now=now)
        camp_service.cancel_camp(
            context=organizer, camp_id=camp["campId"], reason="venue lost", now=now
        )

        outcome = camp_service.send_due_reminders(now=now)
        # Everything in the window is cancelled, so nothing may be sent.
        assert outcome["sent"] == 0, (
            f"a cancelled camp must not produce reminders, got {outcome}"
        )
