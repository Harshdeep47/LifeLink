"""Seed the synthetic demo dataset (spec Part 11).

Properties the spec requires, all implemented here:

* **Idempotent** -- re-running produces the same state, not duplicates.
* **Deterministic** -- a fixed seed and fixed ids, so the demo is reproducible
  and so screenshots and documentation stay accurate.
* **Resettable** -- ``--reset`` clears the demo data first.
* **Validated** -- ``--validate`` checks the dataset covers every required case.
* **Guarded against production** -- refuses to run unless the environment is
  local or development, and every record is marked synthetic.

There is NO verified institutional dataset for this project. Every organization,
facility, batch, camp and request created here is invented. Coordinates are
plausible locations in Punjab and Chandigarh; the institutions at them are not
real and are not partners.

    python scripts/seed_demo.py                 seed
    python scripts/seed_demo.py --reset         wipe demo data, then seed
    python scripts/seed_demo.py --validate      check coverage only
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

os.environ.setdefault("LIFELINK_ENV", "local")
os.environ.setdefault("DYNAMODB_ENDPOINT", "http://localhost:8000")
os.environ.setdefault("AWS_REGION", "ap-southeast-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")

SEED = 20261115
UTC = timezone.utc

DEMO_MARKERS = {"demoData": True, "dataSource": "SYNTHETIC", "environment": "DEVELOPMENT"}

#: Facilities whose O-negative PRBC stock is set exclusively by
#: ``seed_showcase_inventory``. Kept at module level so the generic inventory
#: loop and the showcase loop cannot disagree about the list.
SHOWCASE_FACILITIES = (
    "fac-patiala-1",
    "fac-patiala-2",
    "fac-patiala-3",
    "fac-nabha-1",
    "fac-rajpura-1",
    "fac-zirakpur-1",
    "fac-ambala-1",
)

# Plausible coordinates in the demo geography. The institutions are invented.
#
# The coordinates are real city centres, because the distance and ranking
# behaviour is only demonstrable against real distances -- that is what exposed
# the geohash coverage defect. The *facilities* placed at them do not exist.
# Every seeded facility name carries a "(DEMO)" suffix and the three synthetic
# markers for exactly this reason: a plausible coordinate must never be read as
# a claim that an institution is there.
CITIES = {
    "Patiala": (30.3398, 76.3869),
    "Chandigarh": (30.7333, 76.7794),
    "Jalandhar": (31.3260, 75.5762),
    "Mohali": (30.7046, 76.7179),
    "Rajpura": (30.4844, 76.5944),
    "Ludhiana": (30.9010, 75.8573),
    "Amritsar": (31.6340, 74.8723),
    "Bathinda": (30.2110, 74.9455),
    "Ambala": (30.3782, 76.7767),
    "Zirakpur": (30.6425, 76.8173),
    "Nabha": (30.3752, 76.1517),
    "Sangrur": (30.2458, 75.8421),
    # --- Localities near Patiala -------------------------------------------
    # Camp discovery is limited to a 20 km radius by the camps table's single
    # geohash precision (see KNOWN_LIMITATIONS). Seeding camps only in distant
    # cities meant a Patiala search returned one result and the feature looked
    # empty. These are real localities within that radius, so discovery has
    # something to find at the radius it can actually serve.
    "Sanaur": (30.3086, 76.4617),
    "Bahadurgarh": (30.3707, 76.4344),
    "Devigarh": (30.4340, 76.2590),
    "Ghanaur": (30.4247, 76.6517),
    "Bhadson": (30.1878, 76.1947),
    "Shambhu": (30.4594, 76.5531),
    "Patran": (30.1197, 76.0531),
    # --- Localities near Chandigarh / Mohali --------------------------------
    "Panchkula": (30.6942, 76.8606),
    "Kharar": (30.7463, 76.6469),
    "Dera Bassi": (30.5881, 76.8419),
}


def guard_environment() -> None:
    """Refuse to seed anything that might be production (spec 11.3)."""
    env = os.environ.get("LIFELINK_ENV", "local").lower()
    if env not in ("local", "dev", "development", "test"):
        print(f"REFUSING TO SEED: LIFELINK_ENV is '{env}'.")
        print("Synthetic demo data must never be seeded into staging or production.")
        raise SystemExit(2)
    endpoint = os.environ.get("DYNAMODB_ENDPOINT", "")
    if env in ("local", "test") and not endpoint:
        print("REFUSING TO SEED: local mode requires DYNAMODB_ENDPOINT to be set.")
        print("This prevents a local seed run from writing to real AWS tables.")
        raise SystemExit(2)
    if endpoint and "amazonaws.com" in endpoint:
        print("REFUSING TO SEED: DYNAMODB_ENDPOINT points at real AWS.")
        raise SystemExit(2)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


class DemoSeeder:
    def __init__(self, now: datetime):
        from repositories.alert_repo import AlertRepository
        from repositories.camp_repo import CampRepository, DonationRepository
        from repositories.emergency_repo import EmergencyRepository
        from repositories.facility_repo import FacilityRepository
        from repositories.identity_repo import IdentityRepository
        from repositories.inventory_repo import InventoryRepository
        from repositories.platform_repo import NotificationRepository

        self.now = now
        self.rng = random.Random(SEED)
        self.identity = IdentityRepository()
        self.facilities = FacilityRepository()
        self.inventory = InventoryRepository()
        self.camps = CampRepository()
        self.donations = DonationRepository()
        self.emergency = EmergencyRepository()
        self.alerts = AlertRepository()
        self.notifications = NotificationRepository()
        self.summary: dict[str, int] = {}

    # --- organizations and users ---

    def seed_organizations(self) -> list[dict]:
        from repositories.identity_repo import OrganizationStatus, OrganizationType

        specs = [
            # (id, name, type, status) -- a mix of verified, pending and suspended
            ("org-bb-patiala-1", "Rajindra Civil Blood Centre (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-bb-patiala-2", "Patiala Community Blood Bank (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-bb-chd-1", "Sector 16 Regional Blood Centre (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-bb-chd-2", "Tricity Voluntary Blood Bank (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.PENDING_VERIFICATION),
            ("org-bb-jal-1", "Doaba Blood Services (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-bb-ludh-1", "Ludhiana Metro Blood Bank (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.SUSPENDED),
            # Owners of the extended demonstration facilities.
            ("org-bb-ambala-1", "Ambala Cantt Blood Centre (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-bb-amritsar-1", "Majitha Road Blood Bank (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-bb-bathinda-1", "Malwa Regional Blood Centre (DEMO)",
             OrganizationType.BLOOD_BANK, OrganizationStatus.VERIFIED),
            ("org-hosp-patiala-1", "Patiala General Hospital (DEMO)",
             OrganizationType.HOSPITAL, OrganizationStatus.VERIFIED),
            ("org-hosp-chd-1", "Chandigarh Trauma Centre (DEMO)",
             OrganizationType.HOSPITAL, OrganizationStatus.VERIFIED),
            ("org-hosp-jal-1", "Doaba Multispeciality Hospital (DEMO)",
             OrganizationType.HOSPITAL, OrganizationStatus.PENDING_VERIFICATION),
            ("org-hosp-susp-1", "Northern Care Hospital (DEMO)",
             OrganizationType.HOSPITAL, OrganizationStatus.SUSPENDED),
            ("org-camp-1", "Punjab Youth Blood Donors Society (DEMO)",
             OrganizationType.CAMP_ORGANIZER, OrganizationStatus.VERIFIED),
            ("org-camp-2", "Tricity Rotary Donors (DEMO)",
             OrganizationType.CAMP_ORGANIZER, OrganizationStatus.VERIFIED),
        ]
        created = []
        for org_id, name, org_type, status in specs:
            try:
                self.identity.create_organization(
                    organization_id=org_id,
                    name=name,
                    org_type=org_type.value,
                    status=status.value,
                    now=self.now,
                    extra={**DEMO_MARKERS},
                )
            except Exception:
                pass  # idempotent: already present
            created.append({"organizationId": org_id, "name": name,
                            "type": org_type.value, "status": status.value})
        self.summary["organizations"] = len(created)
        return created

    def seed_users(self) -> list[dict]:
        specs = [
            # Donors
            ("user-donor-1", "aman.donor@demo.invalid", "Aman (DEMO Donor)", ["DONOR"], None),
            ("user-donor-2", "priya.donor@demo.invalid", "Priya (DEMO Donor)", ["DONOR"], None),
            ("user-donor-3", "rohit.donor@demo.invalid", "Rohit (DEMO Donor)", ["DONOR"], None),
            ("user-donor-4", "simran.donor@demo.invalid", "Simran (DEMO Donor)", ["DONOR"], None),
            ("user-donor-5", "vikram.donor@demo.invalid", "Vikram (DEMO Donor)", ["DONOR"], None),
            # Blood bank staff and admins
            ("user-bb-admin-1", "bbadmin1@demo.invalid", "Blood Bank Admin (DEMO)",
             ["BLOOD_BANK_ADMIN"], "org-bb-patiala-1"),
            ("user-bb-staff-1", "bbstaff1@demo.invalid", "Blood Bank Staff (DEMO)",
             ["BLOOD_BANK_STAFF"], "org-bb-patiala-1"),
            ("user-bb-admin-2", "bbadmin2@demo.invalid", "Chandigarh BB Admin (DEMO)",
             ["BLOOD_BANK_ADMIN"], "org-bb-chd-1"),
            ("user-bb-admin-3", "bbadmin3@demo.invalid", "Jalandhar BB Admin (DEMO)",
             ["BLOOD_BANK_ADMIN"], "org-bb-jal-1"),
            # Hospital roles -- note staff vs authorizer
            ("user-hosp-staff-1", "hospstaff1@demo.invalid", "Hospital Staff (DEMO)",
             ["HOSPITAL_STAFF"], "org-hosp-patiala-1"),
            ("user-hosp-auth-1", "hospauth1@demo.invalid", "Dr. Authorizer (DEMO)",
             ["HOSPITAL_AUTHORIZER"], "org-hosp-patiala-1"),
            ("user-hosp-admin-1", "hospadmin1@demo.invalid", "Hospital Admin (DEMO)",
             ["HOSPITAL_ADMIN"], "org-hosp-patiala-1"),
            ("user-hosp-auth-2", "hospauth2@demo.invalid", "Dr. Trauma Authorizer (DEMO)",
             ["HOSPITAL_AUTHORIZER"], "org-hosp-chd-1"),
            # A suspended account, for testing that a valid token is not enough
            ("user-suspended-1", "suspended@demo.invalid", "Suspended User (DEMO)",
             ["BLOOD_BANK_ADMIN"], "org-bb-patiala-2"),
            # Camp roles
            ("user-camp-org-1", "camporg1@demo.invalid", "Camp Organizer (DEMO)",
             ["CAMP_ORGANIZER"], "org-camp-1"),
            ("user-camp-staff-1", "campstaff1@demo.invalid", "Camp Staff (DEMO)",
             ["CAMP_STAFF"], "org-camp-1"),
            ("user-camp-org-2", "camporg2@demo.invalid", "Rotary Organizer (DEMO)",
             ["CAMP_ORGANIZER"], "org-camp-2"),
            # Platform admin
            ("user-admin-1", "admin@demo.invalid", "Platform Admin (DEMO)",
             ["PLATFORM_ADMIN"], None),
        ]
        created = []
        for user_id, email, name, roles, org in specs:
            status = "SUSPENDED" if user_id == "user-suspended-1" else "ACTIVE"
            try:
                self.identity.create_user(
                    user_id=user_id,
                    email=email,
                    display_name=name,
                    roles=roles,
                    organization_id=org,
                    account_status=status,
                    now=self.now,
                    extra={**DEMO_MARKERS},
                )
            except Exception:
                pass
            # Consent on for most donors so notification flows are demonstrable;
            # one donor is opted out so suppression is demonstrable too.
            if "DONOR" in roles:
                opted_in = user_id != "user-donor-5"
                self.notifications.save_preferences(
                    user_id,
                    {
                        "channels": ["IN_APP", "EMAIL"],
                        "consentGiven": opted_in,
                        "campNotifications": opted_in,
                        "alertNotifications": opted_in,
                        "emergencyNotifications": opted_in,
                        "notificationRadiusKm": 10,
                        "extendedRadiusKm": 20,
                        **DEMO_MARKERS,
                    },
                )
            created.append({"userId": user_id, "roles": roles, "organizationId": org,
                            "accountStatus": status})
        self.summary["users"] = len(created)
        return created

    # --- facilities ---

    def seed_facilities(self) -> list[dict]:
        specs = [
            ("fac-patiala-1", "org-bb-patiala-1", "Rajindra Civil Blood Centre (DEMO)",
             "Patiala", "VERIFIED", 0.0, 0.0),
            ("fac-patiala-2", "org-bb-patiala-2", "Patiala Community Blood Bank (DEMO)",
             "Patiala", "UNVERIFIED", 0.018, -0.012),
            ("fac-rajpura-1", "org-bb-patiala-1", "Rajpura Collection Centre (DEMO)",
             "Rajpura", "VERIFIED", 0.0, 0.0),
            ("fac-chd-1", "org-bb-chd-1", "Sector 16 Regional Blood Centre (DEMO)",
             "Chandigarh", "VERIFIED", 0.0, 0.0),
            ("fac-chd-2", "org-bb-chd-2", "Tricity Voluntary Blood Bank (DEMO)",
             "Chandigarh", "UNVERIFIED", -0.021, 0.016),
            ("fac-mohali-1", "org-bb-chd-1", "Mohali Satellite Centre (DEMO)",
             "Mohali", "VERIFIED", 0.0, 0.0),
            ("fac-jal-1", "org-bb-jal-1", "Doaba Blood Services (DEMO)",
             "Jalandhar", "VERIFIED", 0.0, 0.0),
            ("fac-ludh-1", "org-bb-ludh-1", "Ludhiana Metro Blood Bank (DEMO)",
             "Ludhiana", "VERIFIED", 0.0, 0.0),
            # --- Extended demonstration set -------------------------------------
            # Added so that discovery has enough geographic spread to rank
            # meaningfully, and so that radius filtering has something to
            # exclude. The two Patiala-adjacent entries below exist to make the
            # "nearest is not best" scenarios possible at all (see
            # seed_showcase_inventory).
            ("fac-patiala-3", "org-bb-patiala-2", "Urban Estate Donor Centre (DEMO)",
             "Patiala", "VERIFIED", 0.031, 0.024),
            ("fac-nabha-1", "org-bb-patiala-1", "Nabha Rural Blood Unit (DEMO)",
             "Nabha", "VERIFIED", 0.0, 0.0),
            ("fac-zirakpur-1", "org-bb-chd-1", "Zirakpur Transfusion Point (DEMO)",
             "Zirakpur", "VERIFIED", 0.0, 0.0),
            ("fac-ambala-1", "org-bb-ambala-1", "Ambala Cantt Blood Centre (DEMO)",
             "Ambala", "VERIFIED", 0.0, 0.0),
            ("fac-amritsar-1", "org-bb-amritsar-1", "Majitha Road Blood Bank (DEMO)",
             "Amritsar", "VERIFIED", 0.0, 0.0),
            ("fac-amritsar-2", "org-bb-amritsar-1", "Golden City Donor Centre (DEMO)",
             "Amritsar", "UNVERIFIED", -0.026, 0.019),
            ("fac-bathinda-1", "org-bb-bathinda-1", "Malwa Regional Blood Centre (DEMO)",
             "Bathinda", "VERIFIED", 0.0, 0.0),
            ("fac-sangrur-1", "org-bb-bathinda-1", "Sangrur District Blood Unit (DEMO)",
             "Sangrur", "VERIFIED", 0.0, 0.0),
        ]
        created = []
        for fac_id, org_id, name, city, verification, d_lat, d_lon in specs:
            base_lat, base_lon = CITIES[city]

            # Every facility gets a deterministic offset from its city centre,
            # derived from its own id.
            #
            # Twelve facilities previously carried an offset of exactly
            # (0.0, 0.0), which placed them on the city centroid. For Patiala
            # that is the same coordinate the interface uses as its default
            # search origin, so "Rajindra Civil Blood Centre" reported a
            # distance of 0.0 km from a user who had never shared their
            # location — which reads as "you are standing in the blood bank".
            #
            # A real blood bank is not at the geometric centre of its city, so
            # the honest fix is to place each one at a distinct plausible
            # address rather than to adjust a displayed number. Derived from a
            # hash of the id, not from the shared RNG, so a facility's
            # position does not move when unrelated seed data is added or
            # reordered.
            digest = hashlib.sha256(fac_id.encode("utf-8")).digest()
            # Roughly +/- 0.035 degrees, about 4 km: inside the city, never on
            # its centre, and far enough apart to be visibly distinct.
            jitter_lat = ((digest[0] / 255) - 0.5) * 0.07
            jitter_lon = ((digest[1] / 255) - 0.5) * 0.07
            # Keep a minimum separation from the centroid so no facility can
            # round to 0.0 km from a city-centre origin.
            if abs(jitter_lat) < 0.008:
                jitter_lat = 0.008 if jitter_lat >= 0 else -0.008
            if abs(jitter_lon) < 0.008:
                jitter_lon = 0.008 if jitter_lon >= 0 else -0.008
            d_lat += jitter_lat
            d_lon += jitter_lon
            facility = {
                "facilityId": fac_id,
                "organizationId": org_id,
                "name": name,
                "facilityType": "BLOOD_BANK",
                "address": f"{self.rng.randint(1, 120)} Demo Road, {city}",
                "city": city,
                "state": "Chandigarh" if city == "Chandigarh" else "Punjab",
                "latitude": round(base_lat + d_lat, 6),
                "longitude": round(base_lon + d_lon, 6),
                "contactPhone": "+91-00000-00000",
                "operatingHours": "09:00-17:00 IST (DEMO)",
                "verificationStatus": verification,
                # fac-chd-2 deliberately has NO inventory, to demonstrate UNKNOWN
                "inventoryKnown": fac_id != "fac-chd-2",
                **DEMO_MARKERS,
            }
            self.facilities.upsert_facility(facility)
            created.append({"facilityId": fac_id, "city": city,
                            "verificationStatus": verification})
        self.summary["facilities"] = len(created)
        return created

    # --- inventory ---

    def seed_inventory(self) -> dict:
        """Batches covering every case the spec lists.

        Freshness spread (fresh/aging/stale/outdated), expiry spread (healthy /
        near-expiry / expired), quarantined stock, verified and unverified
        facilities, and one facility with no inventory at all.
        """
        from domain.blood import ALL_COMPONENTS, ALL_GROUPS, BatchStatus, BloodGroup, Component
        from repositories.inventory_repo import batch_to_item

        from domain.inventory import Batch

        # (hours since update, label) -- one batch family per freshness band
        freshness_plan = [
            (1, "fresh"), (3, "fresh"),
            (10, "aging"), (18, "aging"),
            (30, "stale"), (40, "stale"),
            (72, "outdated"), (120, "outdated"),
        ]

        # fac-chd-2 is deliberately absent: it is the facility that has never
        # reported, so searches must show it as UNKNOWN rather than as zero.
        facilities_with_stock = [
            "fac-patiala-1", "fac-patiala-2", "fac-rajpura-1",
            "fac-chd-1", "fac-mohali-1", "fac-jal-1", "fac-ludh-1",
            "fac-patiala-3", "fac-nabha-1", "fac-zirakpur-1", "fac-ambala-1",
            "fac-amritsar-1", "fac-amritsar-2", "fac-bathinda-1", "fac-sangrur-1",
        ]

        counters = {
            "total": 0, "available": 0, "expired": 0, "quarantined": 0,
            "near_expiry": 0, "verified": 0, "unverified": 0,
            "fresh": 0, "aging": 0, "stale": 0, "outdated": 0,
        }
        batch_index = 0
        facility_last_update: dict[str, datetime] = {}
        facility_last_verify: dict[str, datetime] = {}

        for facility_id in facilities_with_stock:
            org_id = (self.facilities.get_facility(facility_id) or {}).get(
                "organizationId", "org-bb-patiala-1"
            )
            for group in ALL_GROUPS:
                for component in ALL_COMPONENTS:
                    # Not every facility stocks every component (spec 3.2).
                    if component == Component.PLATELETS and facility_id in (
                        "fac-rajpura-1", "fac-ludh-1"
                    ):
                        continue
                    if component == Component.FFP and facility_id == "fac-rajpura-1":
                        continue
                    # Smaller units genuinely do not stock everything. These
                    # produce NOT_STOCKED cells, which the interface must
                    # distinguish from both zero and unknown.
                    if component == Component.PLATELETS and facility_id in (
                        "fac-nabha-1", "fac-sangrur-1", "fac-amritsar-2"
                    ):
                        continue
                    if component == Component.FFP and facility_id == "fac-sangrur-1":
                        continue
                    # Leave O-negative PRBC alone at the showcase facilities.
                    # seed_showcase_inventory places deliberate batches for
                    # exactly that group and component so the ranking
                    # scenarios can be stated in advance; a generic batch
                    # alongside them changes the aggregate and destroys the
                    # scenario. The first version of this seeder did exactly
                    # that: the "genuinely zero" facility reported 19 units.
                    if (
                        group == BloodGroup.O_NEG
                        and component == Component.PRBC
                        and facility_id in SHOWCASE_FACILITIES
                    ):
                        continue

                    age_hours, band = freshness_plan[batch_index % len(freshness_plan)]
                    batch_index += 1

                    # Deterministic variety of states.
                    slot = batch_index % 12
                    if slot == 3:
                        status = BatchStatus.QUARANTINED
                        expires_at = self.now + timedelta(days=20)
                        units = self.rng.randint(2, 8)
                    elif slot == 7:
                        # Already expired -- must never appear as available.
                        status = BatchStatus.AVAILABLE
                        expires_at = self.now - timedelta(days=2)
                        units = self.rng.randint(1, 6)
                    elif slot == 9:
                        # Near expiry but still eligible.
                        status = BatchStatus.AVAILABLE
                        expires_at = self.now + timedelta(hours=30)
                        units = self.rng.randint(1, 5)
                    elif slot == 11 and group in (BloodGroup.AB_NEG, BloodGroup.B_NEG):
                        # Genuinely zero stock, distinct from unknown.
                        status = BatchStatus.CONSUMED
                        expires_at = self.now + timedelta(days=15)
                        units = 0
                    else:
                        status = BatchStatus.AVAILABLE
                        expires_at = self.now + timedelta(days=self.rng.randint(5, 40))
                        units = self.rng.randint(2, 25)

                    last_updated = self.now - timedelta(hours=age_hours)
                    # Only some batches have independent verification -- the whole
                    # point of ADR-0003 is that these two differ.
                    verified_at = (
                        self.now - timedelta(hours=self.rng.randint(1, 60))
                        if batch_index % 3 == 0
                        else None
                    )

                    batch = Batch(
                        batch_id=f"demo-batch-{batch_index:04d}",
                        facility_id=facility_id,
                        organization_id=org_id,
                        blood_group=group,
                        component=component,
                        available_units=units,
                        status=status,
                        collected_at=self.now - timedelta(days=self.rng.randint(1, 20)),
                        expires_at=expires_at,
                        last_updated_at=last_updated,
                        last_verified_at=verified_at,
                        update_source="SEED" if batch_index % 4 else "API:DEMO_HIS",
                        version=1,
                    )
                    item = {**batch_to_item(batch), **DEMO_MARKERS}
                    self.inventory.put(item)

                    counters["total"] += 1
                    counters[band] += 1
                    if status == BatchStatus.AVAILABLE and expires_at > self.now and units > 0:
                        counters["available"] += 1
                    if expires_at <= self.now:
                        counters["expired"] += 1
                    if status == BatchStatus.QUARANTINED:
                        counters["quarantined"] += 1
                    if self.now < expires_at <= self.now + timedelta(hours=48):
                        counters["near_expiry"] += 1
                    if verified_at:
                        counters["verified"] += 1
                        prev_v = facility_last_verify.get(facility_id)
                        if prev_v is None or verified_at > prev_v:
                            facility_last_verify[facility_id] = verified_at
                    else:
                        counters["unverified"] += 1

                    prev = facility_last_update.get(facility_id)
                    if prev is None or last_updated > prev:
                        facility_last_update[facility_id] = last_updated

        for facility_id, updated_at in facility_last_update.items():
            self.facilities.update(
                pk=f"FACILITY#{facility_id}",
                sk="META",
                update_expression="SET inventoryLastUpdatedAt = :at, inventoryKnown = :k",
                expression_values={":at": iso(updated_at), ":k": True},
            )
        for facility_id, verified_at in facility_last_verify.items():
            self.facilities.update(
                pk=f"FACILITY#{facility_id}",
                sk="META",
                update_expression="SET inventoryLastVerifiedAt = :at",
                expression_values={":at": iso(verified_at)},
            )

        self.summary["inventoryBatches"] = counters["total"]
        return counters

    # --- deliberately engineered discovery scenarios ---

    def seed_showcase_inventory(self) -> dict:
        """Batches placed to prove ranking is not a distance sort.

        The generated inventory above gives breadth. It does not reliably
        produce the *specific* situations that make the ranking defensible,
        because it is driven by a deterministic pattern rather than by the
        question "what would make a demonstration prove something".

        Each scenario below targets one search and is written so the expected
        result can be stated in advance and then checked against the live API.
        All use O-negative PRBC from Patiala, so a single search shows the whole
        story at once.

        Facility distances from Patiala (30.3398, 76.3869), straight line:
          fac-patiala-1    0.0 km   nearest
          fac-patiala-3    4.1 km   near
          fac-patiala-2    2.3 km   near
          fac-nabha-1     22.6 km   mid
          fac-rajpura-1   25.6 km   mid
          fac-zirakpur-1  51.0 km   far
          fac-ambala-1    37.6 km   far-ish
        """
        from domain.blood import BatchStatus, BloodGroup, Component
        from domain.inventory import Batch
        from repositories.inventory_repo import batch_to_item

        group = BloodGroup.O_NEG
        component = Component.PRBC

        # (facility, units, status, expiry days, hours since update, verified, note)
        # A unit count of 0 with CONSUMED means "none in stock", which must read
        # differently from the UNKNOWN of a facility that never reported.
        scenarios = [
            # Nearest, but only 1 unit: a search for 4 units must not rank it first.
            ("fac-patiala-1", 1, BatchStatus.AVAILABLE, 25, 2, True,
             "nearest facility, insufficient stock for a 4-unit request"),
            # Very near, but the data is stale and unverified.
            ("fac-patiala-2", 12, BatchStatus.AVAILABLE, 30, 40, False,
             "near and well stocked, but stale and unverified"),
            # Slightly farther, sufficient, fresh and verified: should win.
            ("fac-patiala-3", 9, BatchStatus.AVAILABLE, 28, 1, True,
             "slightly farther, sufficient, fresh and independently verified"),
            # Expired stock at a mid-distance facility: must be excluded entirely.
            ("fac-nabha-1", 15, BatchStatus.AVAILABLE, -3, 3, True,
             "expired stock, must never appear as available"),
            # Quarantined at another: excluded, with a reason.
            ("fac-rajpura-1", 10, BatchStatus.QUARANTINED, 22, 4, True,
             "quarantined stock, excluded from availability"),
            # Fresh, verified, sufficient but far: appears only at a wide radius.
            ("fac-zirakpur-1", 20, BatchStatus.AVAILABLE, 35, 1, True,
             "fresh, verified and plentiful, but outside a 30 km radius"),
            # Genuinely zero, which is a different answer from "unknown".
            ("fac-ambala-1", 0, BatchStatus.CONSUMED, 26, 6, True,
             "genuinely zero units: 'none in stock', not 'not reported'"),
        ]

        # Guard: the scenario list and the module constant must agree, or the
        # generic loop will add batches the scenarios did not account for.
        scenario_facilities = {s[0] for s in scenarios}
        if scenario_facilities != set(SHOWCASE_FACILITIES):
            raise AssertionError(
                "SHOWCASE_FACILITIES does not match the scenarios: "
                f"{scenario_facilities ^ set(SHOWCASE_FACILITIES)}"
            )

        placed = []
        for i, (facility_id, units, status, expiry_days, age_hours, verified, note) in enumerate(
            scenarios, start=1
        ):
            facility = self.facilities.get_facility(facility_id) or {}
            org_id = facility.get("organizationId", "org-bb-patiala-1")
            last_updated = self.now - timedelta(hours=age_hours)
            batch = Batch(
                batch_id=f"demo-showcase-{i:02d}",
                facility_id=facility_id,
                organization_id=org_id,
                blood_group=group,
                component=component,
                available_units=units,
                status=status,
                collected_at=self.now - timedelta(days=4),
                expires_at=self.now + timedelta(days=expiry_days),
                last_updated_at=last_updated,
                last_verified_at=self.now - timedelta(hours=1) if verified else None,
                update_source="DEMO_SHOWCASE",
                version=1,
            )
            item = batch_to_item(batch)
            item.update(DEMO_MARKERS)
            item["demoScenario"] = note
            self.inventory.put(item)
            placed.append({"facilityId": facility_id, "units": units,
                           "status": status.value, "note": note})

            # Keep the facility's reported-at stamp consistent with the batch, or
            # the freshness badge would contradict the batch it came from.
            self.facilities.update(
                pk=f"FACILITY#{facility_id}",
                sk="META",
                update_expression="SET inventoryLastUpdatedAt = :at, inventoryKnown = :k",
                expression_values={":at": iso(last_updated), ":k": True},
            )

        self.summary["showcaseBatches"] = len(placed)
        return {"total": len(placed), "scenarios": placed}

    # --- camps ---

    def seed_camps(self) -> list[dict]:
        from domain.camps import CampStatus

        specs = [
            ("camp-upcoming-1", "Patiala University Blood Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Patiala", CampStatus.UPCOMING, 5, 150),
            ("camp-upcoming-2", "Chandigarh Sector 17 Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Chandigarh", CampStatus.UPCOMING, 10, 200),
            ("camp-upcoming-3", "Jalandhar Community Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Jalandhar", CampStatus.UPCOMING, 2, 80),
            ("camp-pending-1", "Mohali Corporate Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Mohali", CampStatus.PENDING_APPROVAL, 14, 120),
            ("camp-ongoing-1", "Rajpura Mobile Unit (DEMO)", "org-camp-1",
             "user-camp-org-1", "Rajpura", CampStatus.ONGOING, 0, 60),
            ("camp-completed-1", "Patiala Winter Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Patiala", CampStatus.COMPLETED, -20, 100),
            ("camp-cancelled-1", "Ludhiana Camp (cancelled) (DEMO)", "org-camp-2",
             "user-camp-org-2", "Ludhiana", CampStatus.CANCELLED, 7, 90),
            ("camp-rejected-1", "Unverified Organizer Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Chandigarh", CampStatus.REJECTED, 9, 50),
            # --- Expanded set -------------------------------------------------
            # Within 20 km of Patiala, so discovery is not empty at the radius
            # the camps index can serve. Varied dates, capacities and statuses.
            ("camp-sanaur-1", "Sanaur Village Blood Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Sanaur", CampStatus.UPCOMING, 3, 90),
            ("camp-bahadurgarh-1", "Bahadurgarh Fort Camp (DEMO)", "org-camp-1",
             "user-camp-org-1", "Bahadurgarh", CampStatus.UPCOMING, 6, 70),
            ("camp-devigarh-1", "Devigarh Rural Outreach (DEMO)", "org-camp-2",
             "user-camp-org-2", "Devigarh", CampStatus.UPCOMING, 9, 60),
            ("camp-ghanaur-1", "Ghanaur Community Hall Camp (DEMO)", "org-camp-1",
             "user-camp-org-1", "Ghanaur", CampStatus.UPCOMING, 12, 110),
            ("camp-shambhu-1", "Shambhu Border Donor Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Shambhu", CampStatus.ONGOING, 0, 80),
            ("camp-bhadson-1", "Bhadson Agricultural Society Camp (DEMO)",
             "org-camp-1", "user-camp-org-1", "Bhadson", CampStatus.UPCOMING, 16, 75),
            ("camp-patran-1", "Patran Municipal Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Patran", CampStatus.UPCOMING, 20, 65),
            ("camp-patiala-4", "Thapar Campus Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Patiala", CampStatus.UPCOMING, 1, 180),
            ("camp-patiala-5", "Patiala Railway Colony Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Patiala", CampStatus.ONGOING, 0, 95),
            ("camp-patiala-6", "Patiala Autumn Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Patiala", CampStatus.COMPLETED, -8, 120),
            ("camp-sanaur-2", "Sanaur Youth Club Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Sanaur", CampStatus.CANCELLED, 11, 55),
            # --- Around Chandigarh and Mohali, for a second search origin -----
            ("camp-panchkula-1", "Panchkula Sector 5 Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Panchkula", CampStatus.UPCOMING, 4, 130),
            ("camp-kharar-1", "Kharar Institute Drive (DEMO)", "org-camp-1",
             "user-camp-org-1", "Kharar", CampStatus.UPCOMING, 8, 85),
            ("camp-derabassi-1", "Dera Bassi Industrial Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Dera Bassi", CampStatus.UPCOMING, 13, 100),
            ("camp-mohali-2", "Mohali Phase 7 Camp (DEMO)", "org-camp-1",
             "user-camp-org-1", "Mohali", CampStatus.ONGOING, 0, 70),
            ("camp-chd-3", "Chandigarh Rose Garden Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Chandigarh", CampStatus.COMPLETED, -14, 160),
            # --- Other cities --------------------------------------------------
            ("camp-amritsar-1", "Amritsar Heritage Walk Camp (DEMO)", "org-camp-1",
             "user-camp-org-1", "Amritsar", CampStatus.UPCOMING, 7, 140),
            ("camp-bathinda-1", "Bathinda Cantt Donor Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Bathinda", CampStatus.UPCOMING, 15, 95),
            ("camp-ludhiana-2", "Ludhiana Textile Workers Camp (DEMO)",
             "org-camp-1", "user-camp-org-1", "Ludhiana", CampStatus.UPCOMING, 5, 150),
            ("camp-jalandhar-2", "Jalandhar Sports Complex Camp (DEMO)",
             "org-camp-2", "user-camp-org-2", "Jalandhar", CampStatus.ONGOING, 0, 110),
            ("camp-ambala-1", "Ambala Cantt Volunteers Camp (DEMO)", "org-camp-1",
             "user-camp-org-1", "Ambala", CampStatus.UPCOMING, 10, 100),
            ("camp-nabha-1", "Nabha Civic Centre Camp (DEMO)", "org-camp-2",
             "user-camp-org-2", "Nabha", CampStatus.UPCOMING, 18, 60),
            ("camp-rajpura-2", "Rajpura Market Association Camp (DEMO)",
             "org-camp-1", "user-camp-org-1", "Rajpura", CampStatus.COMPLETED, -5, 80),
        ]
        created = []
        for camp_id, name, org_id, organizer, city, status, days_offset, capacity in specs:
            base_lat, base_lon = CITIES[city]
            if status.value == "ONGOING":
                starts = self.now - timedelta(hours=2)
                ends = self.now + timedelta(hours=4)
            else:
                starts = self.now + timedelta(days=days_offset)
                ends = starts + timedelta(hours=8)

            camp = {
                "campId": camp_id,
                "name": name,
                "description": f"Synthetic demonstration camp in {city}.",
                "organizerOrganizationId": org_id,
                "organizerUserId": organizer,
                "latitude": round(base_lat + self.rng.uniform(-0.01, 0.01), 6),
                "longitude": round(base_lon + self.rng.uniform(-0.01, 0.01), 6),
                "address": f"{self.rng.randint(1, 90)} Demo Grounds, {city}",
                "city": city,
                "startsAt": iso(starts),
                "endsAt": iso(ends),
                "registrationDeadline": iso(starts - timedelta(hours=6)),
                "capacity": capacity,
                "registeredCount": 0,
                "status": status.value,
                "createdAt": iso(self.now - timedelta(days=30)),
                **DEMO_MARKERS,
            }
            item = self.camps._with_indexes(camp)
            # Reminder-window index, used by the scheduled reminder worker.
            item["GSI4PK"] = "REMINDER#WINDOW"
            item["GSI4SK"] = iso(starts)
            self.camps.put(item)
            created.append({"campId": camp_id, "status": status.value, "city": city})

        # Staff assignments, scoped per camp (spec 5.7)
        for camp_id in ("camp-upcoming-1", "camp-ongoing-1", "camp-completed-1"):
            self.camps.assign_staff(
                camp_id=camp_id, user_id="user-camp-staff-1",
                assigned_by="user-camp-org-1", now=self.now,
            )

        self.summary["camps"] = len(created)
        return created

    def seed_registrations_and_donations(self) -> dict:
        """Registrations, attendance and donations in every combination.

        Deliberately includes a registered-but-not-attended donor, an attended
        donor with no donation, a recorded-but-unverified donation and verified
        donations -- so the four-state separation is visible in the demo.
        """
        donors = ["user-donor-1", "user-donor-2", "user-donor-3",
                  "user-donor-4", "user-donor-5"]
        counters = {"registrations": 0, "checkedIn": 0, "recorded": 0, "verified": 0}

        plan = [
            # (camp, donor, checked_in, donation_recorded, donation_verified)
            ("camp-upcoming-1", "user-donor-1", False, False, False),
            ("camp-upcoming-1", "user-donor-2", False, False, False),
            ("camp-upcoming-1", "user-donor-3", False, False, False),
            ("camp-upcoming-2", "user-donor-1", False, False, False),
            ("camp-upcoming-2", "user-donor-4", False, False, False),
            ("camp-ongoing-1", "user-donor-2", True, False, False),
            ("camp-ongoing-1", "user-donor-3", True, True, False),
            ("camp-completed-1", "user-donor-1", True, True, True),
            ("camp-completed-1", "user-donor-2", True, True, True),
            ("camp-completed-1", "user-donor-3", True, True, True),
            ("camp-completed-1", "user-donor-4", True, True, False),
            ("camp-completed-1", "user-donor-5", False, False, False),
        ]

        from domain.blood import BloodGroup, Component

        donor_groups = {
            "user-donor-1": BloodGroup.O_NEG,
            "user-donor-2": BloodGroup.A_POS,
            "user-donor-3": BloodGroup.B_POS,
            "user-donor-4": BloodGroup.AB_POS,
            "user-donor-5": BloodGroup.O_POS,
        }

        donation_seq = 0
        for camp_id, donor, checked_in, recorded, verified in plan:
            registered_at = self.now - timedelta(days=self.rng.randint(1, 25))
            item = {
                "PK": f"CAMP#{camp_id}",
                "SK": f"REG#{donor}",
                "GSI2PK": f"USER#{donor}",
                "GSI2SK": f"REG#{iso(registered_at)}#{camp_id}",
                "entityType": "REGISTRATION",
                "campId": camp_id,
                "userId": donor,
                "registeredAt": iso(registered_at),
                "status": "CHECKED_IN" if checked_in else "REGISTERED",
                "attendanceStatus": "CHECKED_IN" if checked_in else "NOT_ATTENDED",
                **DEMO_MARKERS,
            }
            if checked_in:
                item["checkedInAt"] = iso(registered_at + timedelta(days=1))
                item["checkedInBy"] = "user-camp-staff-1"
                counters["checkedIn"] += 1
            self.camps.put(item)
            counters["registrations"] += 1

            if recorded:
                donation_seq += 1
                donation_id = f"demo-donation-{donation_seq:03d}"
                donated_at = registered_at + timedelta(days=1)
                donation = {
                    "PK": f"USER#{donor}",
                    "SK": f"DONATION#{donation_id}",
                    "GSI1PK": f"CAMP#{camp_id}",
                    "GSI1SK": f"DONATION#{donation_id}",
                    "entityType": "DONATION",
                    "donationId": donation_id,
                    "donorId": donor,
                    "campId": camp_id,
                    "bloodGroup": donor_groups[donor].value,
                    "component": Component.WHOLE_BLOOD.value,
                    "units": 1,
                    "recordedBy": "user-camp-staff-1",
                    "recordedAt": iso(donated_at),
                    "status": "VERIFIED" if verified else "RECORDED",
                    **DEMO_MARKERS,
                }
                if verified:
                    donation["verifiedBy"] = "user-camp-staff-1"
                    donation["verifiedAt"] = iso(donated_at + timedelta(hours=2))
                self.donations.put(donation)
                counters["recorded"] += 1

                if verified:
                    # Ledger entry keyed on donation id -- exactly-once by construction.
                    self.donations.put(
                        {
                            "PK": f"USER#{donor}",
                            "SK": f"LEDGER#{donation_id}",
                            "entityType": "LEDGER_ENTRY",
                            "donationId": donation_id,
                            "donorId": donor,
                            "points": 100,
                            "reason": "VERIFIED_DONATION",
                            "occurredAt": iso(donated_at + timedelta(hours=2)),
                            "verifiedBy": "user-camp-staff-1",
                            **DEMO_MARKERS,
                        }
                    )
                    counters["verified"] += 1

        # Extra historical verified donations so one donor crosses a milestone.
        for n in range(3):
            donation_seq += 1
            donation_id = f"demo-donation-{donation_seq:03d}"
            occurred = self.now - timedelta(days=120 + n * 100)
            self.donations.put(
                {
                    "PK": "USER#user-donor-1",
                    "SK": f"DONATION#{donation_id}",
                    "GSI1PK": "CAMP#camp-completed-1",
                    "GSI1SK": f"DONATION#{donation_id}",
                    "entityType": "DONATION",
                    "donationId": donation_id,
                    "donorId": "user-donor-1",
                    "campId": "camp-completed-1",
                    "bloodGroup": BloodGroup.O_NEG.value,
                    "component": Component.WHOLE_BLOOD.value,
                    "units": 1,
                    "status": "VERIFIED",
                    "recordedAt": iso(occurred),
                    "verifiedAt": iso(occurred + timedelta(hours=1)),
                    "verifiedBy": "user-camp-staff-1",
                    **DEMO_MARKERS,
                }
            )
            self.donations.put(
                {
                    "PK": "USER#user-donor-1",
                    "SK": f"LEDGER#{donation_id}",
                    "entityType": "LEDGER_ENTRY",
                    "donationId": donation_id,
                    "donorId": "user-donor-1",
                    "points": 100,
                    "reason": "VERIFIED_DONATION",
                    "occurredAt": iso(occurred + timedelta(hours=1)),
                    **DEMO_MARKERS,
                }
            )
            counters["recorded"] += 1
            counters["verified"] += 1

        # Keep registeredCount consistent with the registrations written above.
        from collections import Counter

        per_camp = Counter(camp for camp, *_ in plan)
        for camp_id, count in per_camp.items():
            self.camps.update(
                pk=f"CAMP#{camp_id}",
                sk="META",
                update_expression="SET registeredCount = :c",
                expression_values={":c": count},
            )

        self.summary["registrations"] = counters["registrations"]
        self.summary["donations"] = counters["recorded"]
        return counters

    # --- emergency requests ---

    def seed_emergency(self) -> dict:
        from domain.emergency import ClinicalPriority, ProviderResponseType, RequestStatus

        specs = [
            # (id, priority, status, group, component, units, hospital, city)
            ("demo-req-p1-1", ClinicalPriority.P1, RequestStatus.PROVIDERS_NOTIFIED,
             "O-", "PRBC", 4, "org-hosp-patiala-1", "Patiala"),
            ("demo-req-p1-2", ClinicalPriority.P1, RequestStatus.RESPONSES_RECEIVED,
             "AB+", "PLATELETS", 2, "org-hosp-chd-1", "Chandigarh"),
            ("demo-req-p2-1", ClinicalPriority.P2, RequestStatus.HOSPITAL_CERTIFIED,
             "A+", "PRBC", 3, "org-hosp-patiala-1", "Patiala"),
            ("demo-req-p2-2", ClinicalPriority.P2, RequestStatus.RESPONSES_RECEIVED,
             "B+", "FFP", 2, "org-hosp-chd-1", "Chandigarh"),
            ("demo-req-p3-1", ClinicalPriority.P3, RequestStatus.HOSPITAL_CERTIFIED,
             "O+", "WHOLE_BLOOD", 2, "org-hosp-patiala-1", "Patiala"),
            ("demo-req-p3-2", ClinicalPriority.P3, RequestStatus.MATCHING_INITIATED,
             "A-", "PRBC", 1, "org-hosp-chd-1", "Mohali"),
            ("demo-req-uncert-1", None, RequestStatus.VERIFICATION_PENDING,
             "B-", "PRBC", 2, "org-hosp-jal-1", "Jalandhar"),
            ("demo-req-resolved-1", ClinicalPriority.P2, RequestStatus.RESOLVED,
             "O+", "PRBC", 2, "org-hosp-patiala-1", "Patiala"),
            ("demo-req-cancelled-1", ClinicalPriority.P3, RequestStatus.CANCELLED,
             "AB-", "FFP", 1, "org-hosp-chd-1", "Chandigarh"),
            ("demo-req-expired-1", ClinicalPriority.P2, RequestStatus.EXPIRED,
             "A+", "PLATELETS", 2, "org-hosp-patiala-1", "Patiala"),
        ]

        counters = {"requests": 0, "responses": 0, "partial": 0}

        for req_id, priority, status, group, component, units, hospital, city in specs:
            base_lat, base_lon = CITIES[city]
            created_at = self.now - timedelta(hours=self.rng.randint(1, 30))
            required_by = (
                self.now - timedelta(hours=2)
                if status == RequestStatus.EXPIRED
                else self.now + timedelta(hours=self.rng.randint(3, 48))
            )
            item = {
                "PK": f"REQUEST#{req_id}",
                "SK": "META",
                "entityType": "EMERGENCY_REQUEST",
                "requestId": req_id,
                "bloodGroup": group,
                "component": component,
                "requiredUnits": units,
                "latitude": round(base_lat + self.rng.uniform(-0.01, 0.01), 6),
                "longitude": round(base_lon + self.rng.uniform(-0.01, 0.01), 6),
                "requiredBy": iso(required_by),
                "contactName": "Demo Contact",
                "contactPhone": "+91-00000-00000",
                "requesterOrganizationId": hospital,
                "createdBy": "user-hosp-staff-1",
                "consentGiven": True,
                "consentRecordedAt": iso(created_at),
                "status": status.value,
                "clinicalPriority": priority.value if priority else None,
                "effectivePriority": priority.value if priority else "P3",
                "hospitalVerificationState": (
                    "PENDING_VERIFICATION" if hospital == "org-hosp-jal-1" else "VERIFIED"
                ),
                "createdAt": iso(created_at),
                "GSI2PK": f"ORG#{hospital}",
                "GSI2SK": f"REQUEST#{iso(created_at)}#{req_id}",
                "GSI4PK": "ACTIVE",
                "GSI4SK": iso(required_by),
                **DEMO_MARKERS,
            }
            if priority:
                item["certifiedBy"] = "user-hosp-auth-1"
                item["certifiedByRole"] = "HOSPITAL_AUTHORIZER"
                item["certifyingOrganizationId"] = hospital
                item["certifiedAt"] = iso(created_at + timedelta(minutes=10))
            # Only non-terminal, dispatchable states belong in the dispatch index.
            if status.value in ("HOSPITAL_CERTIFIED", "MATCHING_INITIATED"):
                item["GSI1PK"] = f"DISPATCH#{status.value}"
                item["GSI1SK"] = f"{item['effectivePriority']}#{iso(created_at)}"

            self.emergency.put(item)
            counters["requests"] += 1

            self.emergency.put(
                {
                    "PK": f"REQUEST#{req_id}",
                    "SK": f"EVENT#{iso(created_at)}#seed0001",
                    "entityType": "REQUEST_EVENT",
                    "eventType": "REQUEST_CREATED",
                    "actorId": "user-hosp-staff-1",
                    "occurredAt": iso(created_at),
                    "detail": {"seeded": True},
                    **DEMO_MARKERS,
                }
            )

            # Provider responses, including a partial offer and a rejection.
            if status in (RequestStatus.PROVIDERS_NOTIFIED, RequestStatus.RESPONSES_RECEIVED):
                providers = [
                    ("org-bb-patiala-1", "fac-patiala-1", ProviderResponseType.ACCEPTED, units),
                    ("org-bb-chd-1", "fac-chd-1", ProviderResponseType.INSUFFICIENT_STOCK,
                     max(1, units - 1)),
                    ("org-bb-jal-1", "fac-jal-1", ProviderResponseType.REJECTED, 0),
                ]
                for provider_org, facility_id, response_type, offered in providers:
                    responded = status == RequestStatus.RESPONSES_RECEIVED
                    row = {
                        "PK": f"REQUEST#{req_id}",
                        "SK": f"RESPONSE#{provider_org}",
                        "GSI3PK": f"PROVIDER#{provider_org}",
                        "GSI3SK": (
                            f"{'RESPONDED' if responded else 'PENDING'}#"
                            f"{iso(created_at)}#{req_id}"
                        ),
                        "entityType": "PROVIDER_RESPONSE",
                        "requestId": req_id,
                        "providerOrganizationId": provider_org,
                        "facilityId": facility_id,
                        "notifiedAt": iso(created_at + timedelta(minutes=15)),
                        "status": "RESPONDED" if responded else "AWAITING_RESPONSE",
                        **DEMO_MARKERS,
                    }
                    if responded:
                        row["responseType"] = response_type.value
                        row["unitsOffered"] = offered
                        row["respondedAt"] = iso(created_at + timedelta(minutes=35))
                        row["respondedBy"] = "user-bb-admin-1"
                        if response_type == ProviderResponseType.INSUFFICIENT_STOCK:
                            counters["partial"] += 1
                    self.emergency.put(row)
                    counters["responses"] += 1

        self.summary["emergencyRequests"] = counters["requests"]
        return counters

    # --- alerts ---

    def seed_alerts(self) -> int:
        specs = [
            ("demo-alert-1", "user-donor-1", "O-", "PRBC", 2, "Patiala", "ACTIVE"),
            ("demo-alert-2", "user-donor-2", "A+", "PLATELETS", 1, "Chandigarh", "ACTIVE"),
            ("demo-alert-3", "user-donor-3", "AB-", "FFP", 1, "Jalandhar", "ACTIVE"),
            ("demo-alert-4", "user-donor-4", "B+", "PRBC", 3, "Patiala", "CANCELLED"),
            ("demo-alert-5", "user-donor-1", "O+", "WHOLE_BLOOD", 2, "Mohali", "EXPIRED"),
        ]
        from domain.geo import encode_geohash

        count = 0
        for alert_id, user, group, component, units, city, status in specs:
            base_lat, base_lon = CITIES[city]
            created_at = self.now - timedelta(hours=self.rng.randint(1, 12))
            expires_at = (
                self.now - timedelta(hours=1)
                if status == "EXPIRED"
                else self.now + timedelta(hours=18)
            )
            geohash5 = encode_geohash(base_lat, base_lon, 5)
            item = {
                "PK": f"ALERT#{alert_id}",
                "SK": "META",
                "entityType": "AVAILABILITY_ALERT",
                "alertId": alert_id,
                "userId": user,
                "bloodGroup": group,
                "component": component,
                "requiredUnits": units,
                "latitude": base_lat,
                "longitude": base_lon,
                "radiusKm": 15,
                "geohash5": geohash5,
                "requiredBy": iso(self.now + timedelta(hours=24)),
                "expiresAt": iso(expires_at),
                "expiresAtEpoch": int(expires_at.timestamp()),
                "status": status,
                "createdAt": iso(created_at),
                "notifyChannels": ["IN_APP", "EMAIL"],
                "isReservation": False,
                "GSI1PK": f"USER#{user}",
                "GSI1SK": f"{status}#{iso(created_at)}",
                **DEMO_MARKERS,
            }
            if status == "ACTIVE":
                item["GSI2PK"] = f"MATCH#{geohash5}#{group}#{component}"
                item["GSI2SK"] = f"ACTIVE#{iso(expires_at)}"
            self.alerts.put(item)
            count += 1
        self.summary["alerts"] = count
        return count


def wipe_demo_data() -> int:
    """Delete every item marked as demo data.

    Uses a scan, which is forbidden on user-facing paths but is the right tool
    for an offline maintenance job -- and this one logs that it did so.
    """
    from repositories.dynamo import Tables, get_table

    removed = 0
    for logical in Tables.all():
        table = get_table(logical)
        start_key = None
        while True:
            kwargs = {"ProjectionExpression": "PK, SK, demoData"}
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = table.scan(**kwargs)
            with table.batch_writer() as batch:
                for item in response.get("Items", []):
                    if item.get("demoData"):
                        batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                        removed += 1
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
    print(f"OFFLINE MAINTENANCE SCAN: removed {removed} demo items")
    return removed


def validate_dataset() -> int:
    """Check the seeded dataset actually covers every case the spec requires."""
    from domain.blood import ALL_COMPONENTS, ALL_GROUPS
    from repositories.dynamo import get_table
    from repositories.dynamo import Tables

    checks: list[tuple[str, bool, str]] = []

    inventory = get_table(Tables.INVENTORY).scan().get("Items", [])
    batches = [i for i in inventory if i.get("entityType") == "BATCH"]

    groups_present = {b["bloodGroup"] for b in batches}
    components_present = {b["component"] for b in batches}
    statuses = {b["status"] for b in batches}

    checks.append(("all 8 blood groups present",
                   groups_present >= {g.value for g in ALL_GROUPS},
                   f"{len(groups_present)}/8"))
    checks.append(("all 4 components present",
                   components_present >= {c.value for c in ALL_COMPONENTS},
                   f"{len(components_present)}/4"))
    checks.append(("quarantined stock present", "QUARANTINED" in statuses, ""))
    checks.append(("consumed/zero stock present", "CONSUMED" in statuses, ""))

    now = datetime.now(UTC)
    expired = [b for b in batches if b.get("expiresAt", "") < iso(now)]
    near = [
        b for b in batches
        if iso(now) < b.get("expiresAt", "") < iso(now + timedelta(hours=48))
    ]
    checks.append(("expired batches present", len(expired) > 0, f"{len(expired)}"))
    checks.append(("near-expiry batches present", len(near) > 0, f"{len(near)}"))

    verified = [b for b in batches if b.get("lastVerifiedAt")]
    unverified = [b for b in batches if not b.get("lastVerifiedAt")]
    checks.append(("verified batches present", len(verified) > 0, f"{len(verified)}"))
    checks.append(("unverified batches present", len(unverified) > 0, f"{len(unverified)}"))

    # Freshness spread
    bands = {"fresh": 0, "aging": 0, "stale": 0, "outdated": 0}
    for b in batches:
        updated = b.get("lastUpdatedAt")
        if not updated:
            continue
        age = (now - datetime.fromisoformat(updated.replace("Z", "+00:00"))).total_seconds() / 3600
        if age <= 6:
            bands["fresh"] += 1
        elif age <= 24:
            bands["aging"] += 1
        elif age <= 48:
            bands["stale"] += 1
        else:
            bands["outdated"] += 1
    for band, count in bands.items():
        checks.append((f"{band} inventory present", count > 0, f"{count}"))

    facilities = get_table(Tables.FACILITIES).scan().get("Items", [])
    unknown_inventory = [f for f in facilities if not f.get("inventoryKnown")]
    checks.append(("facility with UNKNOWN inventory present",
                   len(unknown_inventory) > 0, f"{len(unknown_inventory)}"))
    checks.append(("verified and unverified facilities present",
                   len({f.get("verificationStatus") for f in facilities}) > 1, ""))

    camps = [
        c for c in get_table(Tables.CAMPS).scan().get("Items", [])
        if c.get("entityType") == "CAMP"
    ]
    camp_statuses = {c["status"] for c in camps}
    required_camp_states = {"PENDING_APPROVAL", "UPCOMING", "ONGOING", "COMPLETED",
                            "CANCELLED", "REJECTED"}
    checks.append(("all 6 camp lifecycle states present",
                   camp_statuses >= required_camp_states,
                   f"{len(camp_statuses)}/6"))

    donations = [
        d for d in get_table(Tables.DONATIONS).scan().get("Items", [])
        if d.get("entityType") == "DONATION"
    ]
    checks.append(("verified donations present",
                   any(d.get("status") == "VERIFIED" for d in donations), ""))
    checks.append(("unverified donations present",
                   any(d.get("status") == "RECORDED" for d in donations), ""))

    requests = [
        r for r in get_table(Tables.EMERGENCY).scan().get("Items", [])
        if r.get("entityType") == "EMERGENCY_REQUEST"
    ]
    priorities = {r.get("clinicalPriority") for r in requests}
    checks.append(("P1, P2 and P3 requests present",
                   {"P1", "P2", "P3"} <= priorities, str(sorted(p for p in priorities if p))))
    checks.append(("uncertified request present", None in priorities, ""))

    responses = [
        r for r in get_table(Tables.EMERGENCY).scan().get("Items", [])
        if r.get("entityType") == "PROVIDER_RESPONSE"
    ]
    response_types = {r.get("responseType") for r in responses if r.get("responseType")}
    checks.append(("partial stock response present",
                   "INSUFFICIENT_STOCK" in response_types, ""))
    checks.append(("accepted and rejected responses present",
                   {"ACCEPTED", "REJECTED"} <= response_types, ""))

    users = [
        u for u in get_table(Tables.ORGANIZATIONS).scan().get("Items", [])
        if u.get("entityType") == "USER"
    ]
    checks.append(("suspended user present",
                   any(u.get("accountStatus") == "SUSPENDED" for u in users), ""))
    roles_present = {r for u in users for r in u.get("roles", [])}
    checks.append(("multiple distinct roles present", len(roles_present) >= 8,
                   f"{len(roles_present)} roles"))

    all_marked = all(
        b.get("demoData") for b in batches
    ) and all(c.get("demoData") for c in camps)
    checks.append(("every record marked demoData", all_marked, ""))

    print("\nDemo dataset validation")
    print("=" * 66)
    failures = 0
    for label, passed, detail in checks:
        mark = "PASS" if passed else "FAIL"
        if not passed:
            failures += 1
        suffix = f"  ({detail})" if detail else ""
        print(f"  [{mark}] {label}{suffix}")
    print("=" * 66)
    print(f"{len(checks) - failures}/{len(checks)} checks passed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed LifeLink synthetic demo data")
    parser.add_argument("--reset", action="store_true", help="wipe demo data first")
    parser.add_argument("--validate", action="store_true", help="validate only")
    args = parser.parse_args()

    guard_environment()

    if args.validate:
        return validate_dataset()

    if args.reset:
        wipe_demo_data()

    now = datetime.now(UTC)
    seeder = DemoSeeder(now)

    print("Seeding LifeLink synthetic demo data")
    print("DEMO ENVIRONMENT - SYNTHETIC DATA - NOT REAL BLOOD AVAILABILITY")
    print("-" * 66)

    seeder.seed_organizations()
    print(f"  organizations     : {seeder.summary['organizations']}")
    seeder.seed_users()
    print(f"  users             : {seeder.summary['users']}")
    seeder.seed_facilities()
    print(f"  facilities        : {seeder.summary['facilities']}")
    inv = seeder.seed_inventory()
    print(f"  inventory batches : {inv['total']}"
          f" (available {inv['available']}, expired {inv['expired']},"
          f" quarantined {inv['quarantined']}, near-expiry {inv['near_expiry']})")
    print(f"  freshness spread  : fresh {inv['fresh']}, aging {inv['aging']},"
          f" stale {inv['stale']}, outdated {inv['outdated']}")
    print(f"  verification      : verified {inv['verified']}, unverified {inv['unverified']}")
    show = seeder.seed_showcase_inventory()
    print(f"  showcase batches  : {show['total']} (O-negative PRBC near Patiala)")
    for s in show["scenarios"]:
        print(f"      {s['facilityId']:<16} {s['units']:>3} units  {s['note']}")
    seeder.seed_camps()
    print(f"  camps             : {seeder.summary['camps']}")
    reg = seeder.seed_registrations_and_donations()
    print(f"  registrations     : {reg['registrations']} (checked in {reg['checkedIn']})")
    print(f"  donations         : {reg['recorded']} (verified {reg['verified']})")
    em = seeder.seed_emergency()
    print(f"  emergency requests: {em['requests']} (responses {em['responses']},"
          f" partial {em['partial']})")
    seeder.seed_alerts()
    print(f"  availability alerts: {seeder.summary['alerts']}")
    print("-" * 66)
    print("Seed complete. Validate with: python scripts/seed_demo.py --validate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
