"""The real-facility dataset validator.

A validator nobody exercises is decoration. The dangerous record for this
dataset is not malformed, it is *plausible* — a real-sounding hospital with no
source and a coordinate somebody guessed loads cleanly and then tells a user
that blood is somewhere it is not. So each test below builds exactly that kind
of record and checks it is refused.

The script lives in ``scripts/`` rather than ``src/``, so it is imported by
path.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "validate_facility_dataset.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_facility_dataset", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_module()


def good_record(**overrides) -> dict:
    """A record that should pass, so a test can break exactly one thing."""
    record = {
        "facilityId": "real-patiala-1",
        "name": "Example Government Blood Centre",
        "city": "Patiala",
        "district": "Patiala",
        "state": "Punjab",
        "latitude": 30.3398,
        "longitude": 76.3869,
        "coordinateProvenance": "CITY_CENTROID",
        "dataSource": "PUBLIC_REGISTRY",
        "inventoryDataSource": "SYNTHETIC",
        "sourceName": "Punjab SACS - list of licensed blood centres",
        "sourceUrl": "https://punjabsacs.punjab.gov.in/sites/default/files/list.pdf",
        "sourceRetrievedOn": "2026-11-24",
    }
    record.update(overrides)
    return record


def problems_for(record: dict) -> list[str]:
    found, _ = validator.validate({"facilities": [record]})
    return found


class TestBaseline:
    def test_a_fully_sourced_record_passes(self):
        assert problems_for(good_record()) == []

    def test_an_empty_dataset_passes_with_nothing_examined(self):
        problems, examined = validator.validate({"facilities": []})
        assert problems == []
        assert examined == 0

    def test_a_dataset_without_the_key_is_refused(self):
        problems, _ = validator.validate({})
        assert problems and "no 'facilities' key" in problems[0]

    def test_facilities_must_be_a_list(self):
        problems, _ = validator.validate({"facilities": {"a": 1}})
        assert problems and "must be a list" in problems[0]


class TestProvenanceIsMandatory:
    """No source, no record. This is the rule the dataset exists to enforce."""

    @pytest.mark.parametrize(
        "field",
        ["sourceName", "sourceUrl", "sourceRetrievedOn", "coordinateProvenance"],
    )
    def test_a_record_missing_provenance_is_refused(self, field):
        record = good_record()
        del record[field]
        problems = problems_for(record)
        assert any(field in p for p in problems), problems

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_source_is_treated_as_absent(self, blank):
        problems = problems_for(good_record(sourceName=blank))
        assert any("sourceName" in p for p in problems)

    def test_a_search_engine_is_not_a_source(self):
        problems = problems_for(
            good_record(sourceUrl="https://www.google.com/search?q=blood+bank+punjab")
        )
        assert any("search engine" in p for p in problems), problems

    def test_a_placeholder_url_is_not_a_source(self):
        problems = problems_for(good_record(sourceUrl="https://example.invalid/x"))
        assert any("placeholder" in p or "search engine" in p for p in problems)

    def test_a_non_http_source_is_refused(self):
        problems = problems_for(good_record(sourceUrl="ftp://somewhere/list.pdf"))
        assert any("http(s)" in p for p in problems)

    def test_a_malformed_retrieval_date_is_refused(self):
        problems = problems_for(good_record(sourceRetrievedOn="24 Nov 2026"))
        assert any("ISO date" in p for p in problems)


class TestTheTwoAxesStaySeparate:
    """A public listing establishes existence, never stock."""

    def test_stock_may_not_claim_to_be_reported_by_the_facility(self):
        problems = problems_for(good_record(inventoryDataSource="REPORTED_BY_FACILITY"))
        assert any("REPORTED_BY_FACILITY" in p for p in problems), problems

    def test_stock_provenance_must_be_stated_as_synthetic(self):
        problems = problems_for(good_record(inventoryDataSource="UNKNOWN"))
        assert any("must be SYNTHETIC" in p for p in problems)

    def test_a_synthetic_facility_does_not_belong_in_this_file(self):
        problems = problems_for(good_record(dataSource="SYNTHETIC"))
        assert any("PUBLIC_REGISTRY" in p for p in problems)

    def test_a_listing_may_not_be_recorded_as_lifelink_verified(self):
        problems = problems_for(good_record(verificationStatus="VERIFIED"))
        assert any("VERIFIED" in p for p in problems), problems

    def test_unverified_is_acceptable(self):
        assert problems_for(good_record(verificationStatus="UNVERIFIED")) == []


class TestCoordinates:
    def test_transposed_latitude_and_longitude_is_caught(self):
        # 76.38, 30.33 instead of 30.33, 76.38 -- the commonest geographic
        # typo. Without a bounds check it lands in the Arabian Sea and the
        # facility simply never appears in a search.
        problems = problems_for(good_record(latitude=76.3869, longitude=30.3398))
        assert any("outside Punjab" in p for p in problems), problems

    def test_zero_zero_is_refused_as_a_missing_value(self):
        problems = problems_for(good_record(latitude=0, longitude=0))
        assert any("missing value" in p for p in problems), problems

    def test_a_coordinate_elsewhere_in_india_is_refused(self):
        # Mumbai. Real, but not Punjab, so it is either a mistake or belongs
        # to another dataset.
        problems = problems_for(good_record(latitude=19.076, longitude=72.877))
        assert any("outside Punjab" in p for p in problems)

    def test_a_string_coordinate_is_refused(self):
        problems = problems_for(good_record(latitude="30.3398"))
        assert any("must be a number" in p for p in problems)

    def test_a_boolean_is_not_accepted_as_a_number(self):
        # bool is a subclass of int in Python, so this needs its own guard.
        problems = problems_for(good_record(latitude=True))
        assert any("must be a number" in p for p in problems)

    @pytest.mark.parametrize(
        "provenance", ["SURVEYED", "GEOCODED_ADDRESS", "CITY_CENTROID"]
    )
    def test_each_valid_provenance_is_accepted(self, provenance):
        assert problems_for(good_record(coordinateProvenance=provenance)) == []

    def test_an_invented_provenance_value_is_refused(self):
        problems = problems_for(good_record(coordinateProvenance="ROUGHLY_RIGHT"))
        assert any("not one of" in p for p in problems)


class TestIdentifiers:
    def test_a_duplicate_facility_id_is_refused(self):
        a = good_record()
        b = good_record(name="Another Centre", city="Nabha")
        problems, examined = validator.validate({"facilities": [a, b]})
        assert examined == 2
        assert any("duplicate facilityId" in p for p in problems), problems

    def test_distinct_ids_pass(self):
        a = good_record()
        b = good_record(facilityId="real-nabha-1", name="Another", city="Nabha")
        problems, _ = validator.validate({"facilities": [a, b]})
        assert problems == []

    def test_a_non_object_record_is_refused_without_crashing(self):
        problems, _ = validator.validate({"facilities": ["just a string"]})
        assert any("not an object" in p for p in problems)


class TestTheShippedDatasetFile:
    """The file in the repository must itself be loadable."""

    def test_the_dataset_parses_and_validates(self):
        path = ROOT / "data" / "real_facilities.json"
        assert path.is_file(), f"missing dataset at {path}"
        dataset = json.loads(path.read_text(encoding="utf-8"))
        problems, examined = validator.validate(dataset)
        assert problems == [], problems
        # Currently zero, because no source could be read. If this ever fails
        # because records were added, that is good news -- update the number.
        assert examined == 0

    def test_the_example_record_is_not_in_the_loadable_list(self):
        """The illustrative shape must not be mistaken for data."""
        path = ROOT / "data" / "real_facilities.json"
        dataset = json.loads(path.read_text(encoding="utf-8"))
        assert dataset["facilities"] == []
        assert "exampleRecord" in dataset

    def test_the_example_record_would_itself_be_refused(self):
        """Proof the example cannot be copied in unchanged."""
        path = ROOT / "data" / "real_facilities.json"
        dataset = json.loads(path.read_text(encoding="utf-8"))
        example = {
            key: value
            for key, value in dataset["exampleRecord"].items()
            if not key.startswith("$")
        }
        assert problems_for(example) != []
