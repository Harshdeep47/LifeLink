"""The API Gateway stage prefix must be stripped before routing.

This is a deployment-only defect, which is why it survived 341 passing tests
and two template linters. An HTTP API on a named stage serves ``/dev/health``
and reports ``rawPath`` as ``/dev/health``, while the route table is written as
``/health``. Locally there is no stage, so every route matched; deployed, every
route 404ed. The first live request after deployment returned:

    {"error": {"code": "NOT_FOUND", "message": "no route for GET /dev/health"}}

These tests pin the behaviour in both shapes so a local run can catch it.
"""

from __future__ import annotations

import pytest

from handlers.router import strip_stage_prefix


def event(stage: str | None) -> dict:
    if stage is None:
        return {}
    return {"requestContext": {"stage": stage}}


class TestNamedStage:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/dev/health", "/health"),
            ("/dev/facilities", "/facilities"),
            ("/dev/facilities/fac-1/batches", "/facilities/fac-1/batches"),
            ("/dev/", "/"),
            ("/dev", "/"),
        ],
    )
    def test_strips_the_stage(self, raw, expected):
        assert strip_stage_prefix(raw, event("dev")) == expected

    def test_strips_whatever_the_stage_is_called(self):
        """Read from the event, so renaming the stage cannot break routing."""
        assert strip_stage_prefix("/staging/health", event("staging")) == "/health"
        assert strip_stage_prefix("/prod/health", event("prod")) == "/health"

    def test_only_strips_a_whole_segment(self):
        """A path that merely starts with the stage's characters is untouched."""
        assert strip_stage_prefix("/dev-tools/health", event("dev")) == "/dev-tools/health"
        assert strip_stage_prefix("/development/x", event("dev")) == "/development/x"

    def test_strips_only_the_first_occurrence(self):
        """A resource genuinely named after the stage must survive."""
        assert strip_stage_prefix("/dev/camps/dev/x", event("dev")) == "/camps/dev/x"

    def test_leaves_a_path_that_does_not_carry_the_prefix(self):
        """Defensive: a local-shaped event reaching a deployed router."""
        assert strip_stage_prefix("/health", event("dev")) == "/health"


class TestNoPrefixCases:
    def test_default_stage_adds_no_prefix(self):
        assert strip_stage_prefix("/health", event("$default")) == "/health"

    def test_default_stage_does_not_eat_a_path_segment(self):
        assert strip_stage_prefix("/facilities", event("$default")) == "/facilities"

    @pytest.mark.parametrize("stage", [None, "", "   "])
    def test_missing_stage_is_a_passthrough(self, stage):
        """Local invocation and direct Lambda tests have no stage."""
        assert strip_stage_prefix("/health", event(stage)) == "/health"

    def test_absent_request_context(self):
        assert strip_stage_prefix("/health", {}) == "/health"

    def test_null_request_context(self):
        assert strip_stage_prefix("/health", {"requestContext": None}) == "/health"

    def test_root_path(self):
        assert strip_stage_prefix("/", event("dev")) == "/"


class TestRouterIntegration:
    """The router must resolve a stage-prefixed path to the same route."""

    def test_health_resolves_with_and_without_the_prefix(self):
        from handlers.api import build_router

        router = build_router()

        local = router.match("GET", "/health")
        assert local[0] is not None, "local-shaped path must route"

        deployed_raw = strip_stage_prefix("/dev/health", event("dev"))
        deployed = router.match("GET", deployed_raw)
        assert deployed[0] is not None, "stage-prefixed path must route"
        assert deployed[0].path == local[0].path

    def test_a_parameterised_route_keeps_its_parameters(self):
        from handlers.api import build_router

        router = build_router()
        path = strip_stage_prefix("/dev/facilities/fac-patiala-1", event("dev"))
        route, params, _ = router.match("GET", path)
        assert route is not None
        assert params.get("facilityId") == "fac-patiala-1"
