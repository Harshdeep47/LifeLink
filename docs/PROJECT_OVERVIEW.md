# LifeLink — Project Overview

## What it is

A cloud platform for blood availability, blood bank discovery, voluntary
donation and emergency coordination, built to demonstrate production-minded
cloud engineering.

> **DEMO ENVIRONMENT — SYNTHETIC DATA — NOT REAL BLOOD AVAILABILITY**

## The problem

India collects enough blood in aggregate, yet people still wait. The gap is
usually coordination rather than supply: a hospital needs two units of
O-negative within four hours, those units may exist eleven kilometres away, and
nobody on either side knows.

The specific obstacles a person faces:

- No single place to see what nearby facilities hold.
- Published figures that may be hours or days old, with nothing saying which.
- No way to tell a facility reporting zero from one reporting nothing.
- Telephoning takes minutes per facility, and the list to try is itself unknown.
- Compatibility rules are not something a frightened relative should be
  improvising at a counter.

## What it does

| Feature | Capability |
|---|---|
| 1. Inventory | Batch-level stock with expiry, quarantine, independent verification and audit history |
| 2. Discovery | Geospatial search ranked by availability, freshness, verification and distance |
| 3. Camps | Full camp lifecycle, registration, attendance, verified donation, impact ledger |
| 4. Emergency | Hospital-certified priority, deterministic matching, provider responses |
| 5. Frontend | Responsive, accessible React application with six role-based dashboards |
| 6. Security | RBAC, organization isolation, audit trail, structured logging, alarms |
| 7. Infrastructure | AWS SAM template, validated |

## What it deliberately does not do

- **Reserve blood.** Nothing is held. There is no reservation model, so stock
  cannot be double-counted.
- **Decide clinical urgency.** Only authorized hospital personnel certify
  priority, and the scheduler writes a different field.
- **Certify clinical suitability.** Compatibility narrows operational matching
  only, from data that has not been clinically reviewed.
- **Assess fitness to donate.** Interval advice is information and points at
  camp staff.

## Users

| Role | Does | Is refused |
|---|---|---|
| Public | Search facilities and camps | Privileged dashboards |
| Donor | Alerts, camp registration, donation history | Verifying their own donation |
| Blood bank staff | Update stock, quarantine | Corrections and verification |
| Blood bank admin | All staff actions, corrections, verification, API ingestion | Another organization's inventory |
| Hospital staff | Raise and track emergency requests | Certifying clinical priority |
| Hospital authorizer | Certify clinical priority | Certifying for another hospital |
| Camp organizer | Manage camps, assign staff, verify donations | Any inventory permission |
| Camp staff | Check in, record and verify donations | Camps they are not assigned to |
| Platform admin | Verify organizations, suspend accounts, read audit | Acting unaudited |

## Technology

React and Vite on CloudFront and S3. Python 3.14 on AWS Lambda behind an API
Gateway HTTP API. DynamoDB with 12 tables and 24 secondary indexes. Cognito for
identity. SQS with dead-letter queues. Amazon Location Service for maps,
geocoding and routing. AWS SAM for infrastructure.

## Status

657 backend tests and 294 frontend tests passing. Lint clean. Infrastructure
validated by `cfn-lint` and `sam validate --lint`. **Never deployed.**

## Where to read further

Start with [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) for the
seventeen decisions and the alternatives rejected, then Book 1 for the
architecture in full.
