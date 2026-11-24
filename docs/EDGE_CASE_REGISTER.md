# LifeLink — Edge Case Register

Every edge case the specification names, with where it is handled and the test
that pins it. The specification is explicit that these must be implemented and
tested rather than merely listed, so a row with no test is marked as such.

**Status key:** **TESTED** — a named test asserts it · **IMPLEMENTED** — the
protection exists, no dedicated test · **PARTIAL** — handled in part ·
**NOT HANDLED** — stated honestly.

Test file abbreviations: `u/` = `backend/tests/unit/`,
`i/` = `backend/tests/integration/`, `f/` = `frontend/src/test/`.

---

## 1. Inventory

| # | Scenario | Expected behaviour | Where | Test | Status |
|---|---|---|---|---|---|
| I-01 | Concurrent stock updates | Second write fails its version condition; caller re-reads and retries | `inventory_repo.apply_change` | `i/test_inventory_integration.py::test_a_stale_write_is_rejected_not_silently_applied` | **TESTED** |
| I-02 | Duplicate manual submission | Idempotency key claim returns the stored result | `platform_repo.IdempotencyRepository.claim` | `i/test_inventory_integration.py` | **TESTED** |
| I-03 | Duplicate external API event | Same claim mechanism, keyed on event id | `handlers/workers._claim` | `u/test_authorization.py` (claim logic) | **IMPLEMENTED** |
| I-04 | Delayed stale API update | Rejected with `STALE_UPDATE_REJECTED` | `inventory.is_stale_update` | `u/test_inventory_operations.py::test_older_source_timestamp_is_stale` | **TESTED** |
| I-05 | Invalid stock quantity | `ValidationError` before any write | `inventory.apply_stock_operation` | `u/test_inventory_operations.py::test_negative_unit_count_is_rejected` | **TESTED** |
| I-06 | Negative stock attempt | Refused by domain and by condition expression | `apply_stock_operation` + condition | `u/...::test_deducting_more_than_available_is_refused` | **TESTED** |
| I-07 | Expired batch | Ineligible; excluded by the index range | `eligibility.evaluate_batch_eligibility` | `u/test_freshness_and_eligibility.py::test_expired_batch_is_ineligible` | **TESTED** |
| I-08 | Near-expiry batch | Eligible but flagged | `eligibility.is_near_expiry` | `u/...::test_batch_expiring_tomorrow_is_near_expiry` | **TESTED** |
| I-09 | Quarantined batch | Ineligible with reason | `evaluate_batch_eligibility` | `u/...::test_quarantined_batch_is_ineligible` | **TESTED** |
| I-10 | Missing expiry information | Ineligible; creation refused | `evaluate_batch_eligibility` | `u/...::test_missing_expiry_does_not_silently_pass` | **TESTED** |
| I-11 | Incorrect timezone | Naive timestamps rejected at parse | `clock.parse_iso` | `u/test_freshness_and_eligibility.py` | **TESTED** |
| I-12 | Verification timestamp missing | `UNVERIFIED`, never inferred from an update | `freshness.verification_status` | `u/...::test_never_verified_is_unverified` | **TESTED** |
| I-13 | Inventory update without verification | Update sets `lastUpdatedAt` only | `inventory_repo.record_verification` is the sole writer | `i/...::test_an_api_update_does_not_confer_verification` | **TESTED** |
| I-14 | API credentials expired | Ingestion returns 401 from the decorator | `appcore/auth.py` | `u/test_authorization.py` | **IMPLEMENTED** |
| I-15 | External API schema changed | Validation rejects with a named field | `handlers/router.require_int` etc. | — | **IMPLEMENTED** |
| I-16 | External API outage | No effect; ingestion is inbound | n/a | — | **IMPLEMENTED** |
| I-17 | Queue backlog | Age alarm at 5 minutes; bounded consumer concurrency | `template.yaml` `QueueAgeAlarm` | — | **IMPLEMENTED** |
| I-18 | Outbox write failure | Transaction fails; nothing is written | `apply_change_with_audit` | `i/...::test_an_outbox_event_is_written_in_the_same_transaction` | **TESTED** |
| I-19 | Lambda crash mid-operation | Transaction is atomic; outbox row survives | ADR-0005 | `i/test_inventory_integration.py` | **TESTED** |
| I-20 | DynamoDB conditional-write failure | Translated to `CONCURRENT_MODIFICATION`, retried | `dynamo.put(on_conflict="version")` | `i/...::test_a_stale_write_is_rejected` | **TESTED** |
| I-21 | Inventory alert duplicate | Duplicate suppression per alert and facility | `alert_repo.has_recent_match` | `i/test_end_to_end_scenarios.py::TestScenario03` | **TESTED** |
| I-22 | Partial availability | `PARTIAL` state distinct from available | `inventory.summarise_availability` | `u/...::test_partial_when_less_than_requested` | **TESTED** |
| I-23 | Stock unavailable after alert | Revalidated at match time | `alert_service.match_alert` | `i/test_end_to_end_scenarios.py::TestScenario03` | **TESTED** |
| I-24 | Alert expiry | TTL plus an explicit deadline check | `alert_service.match_alert` | — | **IMPLEMENTED** |
| I-25 | User cancellation | Status set, removed from the match index | `alert_repo.set_status` | — | **IMPLEMENTED** |
| I-26 | No matching stock | Empty match list, no notification | `alert_service.match_alert` | `i/...::test_an_unreported_facility_never_matches` | **TESTED** |

## 2. Location

| # | Scenario | Expected behaviour | Where | Test | Status |
|---|---|---|---|---|---|
| L-01 | Geolocation permission denied | Named status, manual search offered | `hooks/useApi.useGeolocation` | — | **IMPLEMENTED** |
| L-02 | GPS unavailable | `unavailable` status with guidance | `useGeolocation` | — | **IMPLEMENTED** |
| L-03 | Inaccurate coordinates | Warning shown when accuracy exceeds 2 km | `useGeolocation` | — | **IMPLEMENTED** |
| L-04 | Location timeout | 10-second timeout, named status | `useGeolocation` | — | **IMPLEMENTED** |
| L-05 | Manual address invalid | Empty result set, no fabricated match | `discovery_service.geocode` | `i/...::test_geocoding_failure_is_reported_not_faked` | **TESTED** |
| L-06 | Geocoding failure | `providerAvailable: false` with a reason | `discovery_service.geocode` | `i/test_end_to_end_scenarios.py::TestScenario10` | **TESTED** |
| L-07 | No facilities in radius | Empty result with guidance | `search_facilities` | `u/test_geo_and_ranking.py` | **TESTED** |
| L-08 | Facility at radius boundary | Included; cell set covers the whole circle | `geo.search_cells` | `u/test_geo_coverage.py::test_cell_set_covers_every_point_on_the_radius_boundary` | **TESTED** |
| L-09 | Duplicate facilities | Deduplicated by facility id across cells | `facility_repo.find_nearby` | — | **IMPLEMENTED** |
| L-10 | Incorrect facility coordinates | Skipped, search continues | `facility_repo.find_nearby` | — | **IMPLEMENTED** |
| L-11 | Provider outage | `RouteResult(available=False)` with reason | `adapters/location.py` | `i/...::test_discovery_survives_a_routing_outage` | **TESTED** |
| L-12 | Provider rate limit | Mapped to `RATE_LIMITED` reason | `AmazonLocationProvider.route` | — | **IMPLEMENTED** |
| L-13 | Route not found | `ROUTE_NOT_FOUND`, no fabricated distance | `AmazonLocationProvider.route` | `i/...::test_a_route_request_reports_unavailable_rather_than_guessing` | **TESTED** |
| L-14 | Invalid route response | Missing fields produce unavailable | `AmazonLocationProvider.route` | — | **IMPLEMENTED** |
| L-15 | Map tile failure | Facility list fallback | `components/FacilityMap.jsx` | — | **IMPLEMENTED** |
| L-16 | Missing attribution | Attribution control enabled | `FacilityMap.jsx` | — | **IMPLEMENTED** |
| L-17 | User location changes mid-search | In-flight request aborted | `hooks/useApi.useApiData` | — | **IMPLEMENTED** |
| L-18 | Stale facility record | Freshness label reflects it | `freshness.freshness_label` | `u/test_freshness_and_eligibility.py` | **TESTED** |
| L-19 | Unknown inventory | `UNKNOWN`, never zero | `summarise_availability` | `u/...::test_unknown_inventory_is_not_converted_to_zero`, `f/StatusBadges.test.jsx` | **TESTED** |
| L-20 | Ineligible inventory | Excluded before ranking | `search_facilities` | `u/test_geo_and_ranking.py` | **TESTED** |
| L-21 | Pagination boundary | Cursor bound to its query | `responses.decode_cursor` | — | **IMPLEMENTED** |
| L-22 | Excessively large radius | Rejected above 100 km | `geo.search_cells` | `u/test_geo_coverage.py::test_radius_above_maximum_is_rejected` | **TESTED** |

## 3. Camps and donors

| # | Scenario | Expected behaviour | Where | Test | Status |
|---|---|---|---|---|---|
| C-01 | Duplicate registration | `DUPLICATE` via conditional put | `camp_repo.register_atomically` | `i/...::test_duplicate_camp_registration_is_refused` | **TESTED** |
| C-02 | Concurrent final-seat registration | Transaction allows exactly one | `register_atomically` | `i/...::test_a_camp_cannot_be_oversubscribed` | **TESTED** |
| C-03 | Camp full | `CAPACITY_EXCEEDED` | `camps.can_register` | `u/test_camps_and_impact.py::test_full_camp_raises_capacity_error` | **TESTED** |
| C-04 | Registration after deadline | `REGISTRATION_CLOSED` | `camps.can_register` | `u/...::test_registration_after_deadline_is_refused` | **TESTED** |
| C-05 | Camp cancellation after registration | Registrants notified | `camp_service.cancel_camp` | `i/test_camp_reminders.py::test_a_cancelled_camp_produces_no_reminder` | **TESTED** |
| C-06 | Camp time change | Reminder window recomputed from `startsAt` | `camp_repo._with_indexes` | `i/test_camp_reminders.py::test_the_index_sort_key_is_the_start_time` | **TESTED** |
| C-07 | Reminder after cancellation | Suppressed by the status re-check | `camps.should_send_reminder` | `u/...::test_no_reminder_for_a_cancelled_camp` | **TESTED** |
| C-08 | Duplicate reminder | Durable dedupe marker | `platform_repo.mark_sent_marker` | `u/...::test_no_duplicate_reminder` | **TESTED** |
| C-09 | User opted out | Suppressed with `CATEGORY_OPTED_OUT` | `notification_service.is_opted_in` | `u/...::test_no_reminder_for_opted_out_user` | **TESTED** |
| C-10 | User changes notification radius | Bounded 1–50 km | `notification_service.save_preferences` | — | **IMPLEMENTED** |
| C-11 | Location unavailable | Manual search unaffected | `CampsPage.jsx` | — | **IMPLEMENTED** |
| C-12 | Duplicate check-in | Refused by condition | `camp_repo.check_in` | `i/test_end_to_end_scenarios.py::TestScenario04` | **TESTED** |
| C-13 | Unauthorized attendance update | Camp-scoped staff check | `camp_service._assert_camp_staff` | `i/...::test_an_organizer_cannot_manage_another_organizations_camp` | **TESTED** |
| C-14 | Donor self-verification | `SELF_VERIFICATION_FORBIDDEN` | `camps.assert_can_verify_donation` | `u/...::test_being_staff_does_not_permit_self_verification`, `i/...::TestScenario09` | **TESTED** |
| C-15 | Duplicate donation credit | Ledger row keyed on donation id | `camp_repo.verify_donation_and_credit` | `i/...::test_replaying_verification_does_not_double_credit` | **TESTED** |
| C-16 | Organizer accessing another's camp | `ForbiddenError` | `camp_service._assert_camp_authority` | `i/test_end_to_end_scenarios.py::TestScenario09` | **TESTED** |
| C-17 | Staff assigned to wrong camp | Staff records are per camp | `camp_repo.is_camp_staff` | `u/test_camps_and_impact.py` | **TESTED** |
| C-18 | Camp staff account suspended | Decorator refuses | `appcore/auth.requires` | `u/...::test_suspended_account_is_blocked` | **TESTED** |
| C-19 | Certificate generation failure | Refused for unverified donations | `camp_service.certificate_data` | — | **IMPLEMENTED** |
| C-20 | Impact score recalculation | Always derived from the ledger | `impact.compute_score` | `u/...::test_score_is_derived_from_the_ledger` | **TESTED** |
| C-21 | Capacity reduced after registration | Existing stand; new refused | `camps.can_register` | `u/...::test_reduced_capacity_below_current_count_blocks_new_registrations` | **TESTED** |
| C-22 | Camp crosses a timezone boundary | All times UTC; IST has no DST | `clock.py`, ADR-0016 | `u/test_camps_and_impact.py` | **PARTIAL** — IST only |

## 4. Emergency coordination

| # | Scenario | Expected behaviour | Where | Test | Status |
|---|---|---|---|---|---|
| E-01 | Duplicate request | Fingerprint plus idempotency key | `emergency_service._fingerprint` | — | **IMPLEMENTED** |
| E-02 | Invalid request details | Validated before creation | `emergency_service.create_request` | `i/test_end_to_end_scenarios.py::TestScenario06` | **TESTED** |
| E-03 | Unauthorized priority change | Permission plus role check | `rbac.py`, `certify_priority` | `u/...::test_only_authorizer_roles_may_certify_priority` | **TESTED** |
| E-04 | Hospital pending verification | Certification refused | `certify_priority` | `i/...::test_a_suspended_hospital_cannot_certify` | **TESTED** |
| E-05 | Hospital rejected | Same path | `certify_priority` | `i/test_end_to_end_scenarios.py::TestScenario06` | **TESTED** |
| E-06 | Hospital verification suspended | Refused, status named in the error | `certify_priority` | `i/...::test_a_suspended_hospital_cannot_certify` | **TESTED** |
| E-07 | Priority authorization revoked mid-workflow | Re-checked at certification | `certify_priority` | `i/test_end_to_end_scenarios.py::TestScenario06` | **TESTED** |
| E-08 | Incorrect compatibility reference | Review status surfaced; loader refuses unlabelled data | `compatibility._load_reference` | `u/test_compatibility.py::test_reference_declares_its_review_status` | **TESTED** |
| E-09 | No compatible facility | Empty candidate list | `run_matching` | `i/...::test_an_unknown_combination_matches_nothing` | **TESTED** |
| E-10 | No eligible stock | Not matched | `find_facilities_with_stock` | `i/test_end_to_end_scenarios.py::TestScenario07` | **TESTED** |
| E-11 | Partial stock | `INSUFFICIENT_STOCK` response type recorded | `emergency.tally_responses` | `u/test_emergency.py::test_units_offered_sums_accepted_and_partial` | **TESTED** |
| E-12 | Concurrent provider responses | Each conditional on its own row | `emergency_repo.submit_response` | `i/...::test_two_providers_offering_the_same_units_are_not_summed` | **TESTED** |
| E-13 | Provider response duplicated | Second fails its condition | `submit_response` | `i/...::test_a_provider_cannot_respond_twice` | **TESTED** |
| E-14 | Response after cancellation | Refused; no edge from a terminal state | `emergency.VALID_TRANSITIONS` | `u/...::test_late_response_after_cancellation_cannot_revive_request` | **TESTED** |
| E-15 | Response after expiry | Same | `submit_response` | `u/test_emergency.py` | **TESTED** |
| E-16 | Stock disappears after acceptance | Revalidated; acceptance refused | `_revalidate_stock` | `i/test_end_to_end_scenarios.py::TestScenario08` | **TESTED** |
| E-17 | Multiple providers claiming overlapping stock | Offers recorded separately, never netted | ADR-0017 | `u/...::test_two_providers_accepting_do_not_reserve_the_same_units` | **TESTED** |
| E-18 | Notification failure | Delivery status records the failure | `notification_service.notify` | — | **IMPLEMENTED** |
| E-19 | Queue backlog | Age alarm | `template.yaml` | — | **IMPLEMENTED** |
| E-20 | P3 starvation | Priority aging | `emergency.compute_effective_priority` | `u/...::test_waiting_p3_overtakes_a_fresh_p2` | **TESTED** |
| E-21 | P1 surge | Dispatcher batch bounded; P1 sorts first | `run_dispatcher` | `u/test_emergency.py::test_higher_priority_sorts_first` | **TESTED** |
| E-22 | Lambda crash during matching | Transitions conditional; next run resumes | `emergency_repo.transition` | `i/test_end_to_end_scenarios.py::TestScenario07` | **TESTED** |
| E-23 | DynamoDB throttling | Adaptive retry plus alarm | `dynamo._resource` | — | **IMPLEMENTED** |
| E-24 | Invalid state transition | Rejected, allowed targets listed | `emergency.assert_transition` | `u/...::test_cannot_jump_straight_to_resolved` | **TESTED** |
| E-25 | Wrong-organization response | `PROVIDER_NOT_NOTIFIED` | `submit_response` | `i/...::test_a_provider_that_was_not_asked_cannot_respond` | **TESTED** |
| E-26 | Deadline passes during matching | Transitioned to `EXPIRED` | `run_matching`, `expire_overdue` | `u/test_emergency.py::test_past_deadline_is_expired` | **TESTED** |

## 5. Shared platform and security

| # | Scenario | Expected behaviour | Where | Test | Status |
|---|---|---|---|---|---|
| S-01 | Valid JWT from suspended account | `ACCOUNT_SUSPENDED` | `appcore/auth.requires` | `u/...::test_suspended_account_is_blocked_despite_valid_token_and_role` | **TESTED** |
| S-02 | Expired token | `UNAUTHENTICATED` | `CognitoTokenVerifier.verify` | — | **IMPLEMENTED** |
| S-03 | Invalid token | `UNAUTHENTICATED` | `verify` | — | **IMPLEMENTED** |
| S-04 | Role changed while session active | Next request uses new roles | `IdentityRepository.get_principal` | `u/test_authorization.py` | **TESTED** |
| S-05 | Cross-organization data access | `CROSS_ORGANIZATION_DENIED` | `requires(resource_owner=...)` | `u/...::test_cross_organization_access_is_denied` | **TESTED** |
| S-06 | IDOR | Ownership resolved centrally | `appcore/auth.py` | `u/...::test_cross_organization_error_does_not_leak_owner` | **TESTED** |
| S-07 | Privilege escalation | Permissions from stored roles only | `rbac.permissions_for` | `u/...::test_unknown_role_grants_nothing` | **TESTED** |
| S-08 | Unauthorized file access | Private buckets, presigned URLs only | `template.yaml` | — | **IMPLEMENTED** |
| S-09 | Expired presigned URL | Short expiry; client requests a new one | design | — | **NOT HANDLED** — no upload flow is built |
| S-10 | Malicious file upload | Content-type and size validation | design | — | **NOT HANDLED** — no upload flow is built |
| S-11 | Secret rotation | Secrets Manager, no secrets in code | `template.yaml` | — | **IMPLEMENTED** |
| S-12 | Cognito outage | Existing tokens work until expiry | `appcore/auth.py` | — | **IMPLEMENTED** |
| S-13 | API Gateway outage | Client surfaces a network error | `api/client.js` | `f/apiClient.test.js::turns a fetch rejection into a readable network error` | **TESTED** |
| S-14 | Lambda outage | 5xx surfaced; retryable classification | `api/client.js` | `f/apiClient.test.js` | **TESTED** |
| S-15 | DynamoDB throttling | `RATE_LIMITED`, retryable | `dynamo.translate_client_error` | `f/apiClient.test.js` | **TESTED** |
| S-16 | SQS redrive | DLQ plus alarm plus runbook | `template.yaml`, `OPERATIONS_RUNBOOK.md` | — | **IMPLEMENTED** |
| S-17 | SNS/SES failure | Delivery result records it | `adapters/notifications.py` | — | **IMPLEMENTED** |
| S-18 | S3 outage or access denial | Cached assets still served | CloudFront | — | **IMPLEMENTED** |
| S-19 | Audit write failure | Transaction fails; change does not commit | `apply_change_with_audit` | `i/...::test_every_stock_change_writes_an_audit_record` | **TESTED** |
| S-20 | Sensitive data in logs | Recursive redaction by key name | `appcore/logging.redact` | — | **IMPLEMENTED** |
| S-21 | Duplicate API request | Idempotency key | `IdempotencyRepository.claim` | `i/test_inventory_integration.py` | **TESTED** |
| S-22 | Browser network interruption | `NETWORK_ERROR`, retryable, readable message | `api/client.js` | `f/apiClient.test.js` | **TESTED** |
| S-23 | Production seed attempted | Three independent guards refuse | `scripts/seed_demo.guard_environment` | — | **IMPLEMENTED** |
| S-24 | Infrastructure deployment failure | CloudFormation rolls back; retained resources survive | `template.yaml` | — | **NOT TESTED** — no deployment has failed since the stack went live |
| S-25 | Backup restoration failure | Documented procedure | `OPERATIONS_RUNBOOK.md` | — | **NOT TESTED** — PITR enabled, never rehearsed |
| S-26 | Regional service limitation | Verified in Phase 0; SMS absent | `PHASE_0_INVENTORY.md` | — | **IMPLEMENTED** |

---

## Summary

| Status | Count |
|---|---|
| **TESTED** | 72 |
| **IMPLEMENTED** (no dedicated test) | 39 |
| **PARTIAL** | 1 |
| **NOT HANDLED / NOT TESTED** | 4 |
| **Total** | 116 |

The four not handled or not tested are disclosed rather than omitted:

- **S-09, S-10** — file upload validation. No upload flow exists in the
  application, so the protections are designed but not built. The S3 bucket is
  provisioned and private.
- **S-24, S-25** — deployment rollback and backup restoration. Both require a
  deployment, and nothing has been deployed.

**C-22** is partial: all timestamps are UTC and conversion is correct, but the
demo geography is IST, which has no daylight saving. A deployment spanning a
DST boundary would need additional testing.
