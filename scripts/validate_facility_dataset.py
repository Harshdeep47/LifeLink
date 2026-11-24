#!/usr/bin/env python
"""Validate the real-facility dataset before anything can load it.

Runs entirely offline: it reads a JSON file and checks it. There is no AWS
call, no network access and no write path anywhere in this script, which is
why it is safe to run at any time.

It exists because the dangerous failure mode for this dataset is not a crash,
it is a *plausible* record. A facility with a real-sounding name, no source and
a coordinate someone guessed will load cleanly, render cleanly, and quietly
tell a user that a hospital they could drive to has blood it does not have. So
every rule below refuses rather than defaults:

  * no source, no record;
  * no coordinate provenance, no record;
  * stock provenance may never be REPORTED_BY_FACILITY in this file;
  * a coordinate must be inside Punjab's bounding box, because a transposed
    latitude and longitude is the most common geographic typo and lands the
    facility in the sea off Somalia rather than failing;
  * identifiers must be unique, so a second load cannot shadow a first.

Usage
-----
    python scripts/validate_facility_dataset.py
    python scripts/validate_facility_dataset.py --file data/real_facilities.json

Exit status is 0 when the dataset is loadable, 1 when it is not.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = ROOT / "data" / "real_facilities.json"

#: Punjab plus a small margin. A record outside this is either a typo or
#: belongs to a different dataset; either way it must not load silently.
PUNJAB_BOUNDS = {"lat": (29.5, 32.6), "lon": (73.8, 76.95)}

REQUIRED = (
    "facilityId",
    "name",
    "city",
    "district",
    "state",
    "latitude",
    "longitude",
    "coordinateProvenance",
    "dataSource",
    "inventoryDataSource",
    "sourceName",
    "sourceUrl",
    "sourceRetrievedOn",
)

VALID_COORDINATE_PROVENANCE = {"SURVEYED", "GEOCODED_ADDRESS", "CITY_CENTROID"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Hosts that are never an acceptable source: they are places you find a
#: source, not the source itself.
NOT_A_SOURCE = (
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "search.",
    "example.invalid",
    "example.com",
)


def _problems_for(index: int, record: dict) -> list[str]:
    """Every reason this one record may not load."""
    where = f"facilities[{index}]"
    name = record.get("name") or "<unnamed>"
    found: list[str] = []

    def fail(message: str) -> None:
        found.append(f"{where} ({name}): {message}")

    for field in REQUIRED:
        value = record.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            fail(f"missing required field '{field}'")

    if record.get("dataSource") != "PUBLIC_REGISTRY":
        fail(
            "dataSource must be PUBLIC_REGISTRY in this file; a synthetic "
            "facility belongs in the demo seeder"
        )

    inventory = record.get("inventoryDataSource")
    if inventory == "REPORTED_BY_FACILITY":
        fail(
            "inventoryDataSource must not be REPORTED_BY_FACILITY: a public "
            "listing says the place exists, not what is on its shelves"
        )
    elif inventory != "SYNTHETIC":
        fail("inventoryDataSource must be SYNTHETIC in this file")

    provenance = record.get("coordinateProvenance")
    if provenance is not None and provenance not in VALID_COORDINATE_PROVENANCE:
        fail(
            f"coordinateProvenance '{provenance}' is not one of "
            f"{sorted(VALID_COORDINATE_PROVENANCE)}"
        )

    for axis, field in (("lat", "latitude"), ("lon", "longitude")):
        value = record.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail(f"{field} must be a number, got {type(value).__name__}")
            continue
        low, high = PUNJAB_BOUNDS[axis]
        if not low <= float(value) <= high:
            fail(
                f"{field} {value} is outside Punjab ({low} to {high}); check "
                "for transposed latitude and longitude"
            )

    if record.get("latitude") == 0 and record.get("longitude") == 0:
        fail("coordinate 0,0 is a missing value, not a location")

    url = str(record.get("sourceUrl") or "")
    if url and not url.lower().startswith(("http://", "https://")):
        fail("sourceUrl must be an http(s) URL")
    if any(bad in url.lower() for bad in NOT_A_SOURCE):
        fail(
            "sourceUrl points at a search engine or placeholder; it must be "
            "the document the fields were read from"
        )

    retrieved = str(record.get("sourceRetrievedOn") or "")
    if retrieved and not ISO_DATE.match(retrieved):
        fail(f"sourceRetrievedOn '{retrieved}' must be an ISO date (YYYY-MM-DD)")

    if record.get("verificationStatus") == "VERIFIED":
        fail(
            "verificationStatus must not be VERIFIED: appearing in a public "
            "listing is not LifeLink confirming the centre operates today"
        )

    return found


def validate(dataset: dict) -> tuple[list[str], int]:
    """Return (problems, number of records examined)."""
    problems: list[str] = []
    facilities = dataset.get("facilities")

    if facilities is None:
        return (["dataset has no 'facilities' key"], 0)
    if not isinstance(facilities, list):
        return ([f"'facilities' must be a list, got {type(facilities).__name__}"], 0)

    seen_ids: dict[str, int] = {}
    for index, record in enumerate(facilities):
        if not isinstance(record, dict):
            problems.append(f"facilities[{index}] is not an object")
            continue
        problems.extend(_problems_for(index, record))

        identifier = record.get("facilityId")
        if isinstance(identifier, str) and identifier:
            if identifier in seen_ids:
                problems.append(
                    f"facilities[{index}]: duplicate facilityId '{identifier}' "
                    f"(already used at facilities[{seen_ids[identifier]}])"
                )
            else:
                seen_ids[identifier] = index

    return (problems, len(facilities))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=str(DEFAULT_DATASET))
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(f"FAIL: no dataset at {path}")
        return 1

    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: {path} is not valid JSON: {exc}")
        return 1

    problems, examined = validate(dataset)

    print(f"dataset: {path}")
    print(f"records examined: {examined}")

    if problems:
        print(f"\n{len(problems)} problem(s) -- this dataset must not be loaded:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if examined == 0:
        # Not an error. An empty dataset is the honest state when no source
        # could be read, and it loads nothing, so nothing can be misstated.
        print(
            "\nPASS (empty): the schema is valid and there are no records to load.\n"
            "No real facility has been recorded. See docs/REAL_FACILITY_DATA.md\n"
            "for why, and for the procedure to add records."
        )
        return 0

    print(f"\nPASS: {examined} record(s) carry a source and may be loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
