#!/usr/bin/env python
"""Dependency vulnerability gate: the seventh verification gate.

Runs ``pip-audit`` over the backend requirements and ``npm audit`` over the
frontend, and decides what should fail a build.

The decision worth explaining is the split between runtime and development
dependencies, because treating them alike produces one of two bad outcomes: a
gate that blocks on a vulnerability in a test runner that never ships, or a
gate so lenient that a real one slides past.

*   **Runtime dependencies fail the gate at any severity.** These ship to a
    browser or run inside Lambda. This is not theoretical: the first run of
    this gate found a critical XSS in ``maplibre-gl`` and a high-severity open
    redirect in ``react-router-dom``, both of which reach users.
*   **Development dependencies are reported and do not fail it.** A prototype
    pollution flaw in ``tinypool``, reachable only through ``vitest`` on a
    developer's machine, is a real finding and a bad reason to block a
    deployment. They are printed in full every run so they cannot be forgotten,
    and the count is recorded.

That asymmetry is a judgement, not a rule handed down, so it is stated here
rather than buried in a flag.

Usage::

    python scripts/security_audit.py
    python scripts/security_audit.py --strict   # dev findings fail too
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

SEVERITY_ORDER = ["critical", "high", "moderate", "low", "info"]


def find_npm() -> str | None:
    for candidate in ("npm.cmd", "npm"):
        found = shutil.which(candidate)
        if found:
            return found
    for path in (
        Path(r"C:\Program Files\nodejs\npm.cmd"),
        Path(r"C:\Program Files (x86)\nodejs\npm.cmd"),
    ):
        if path.is_file():
            return str(path)
    return None


def run_pip_audit() -> tuple[int, list[dict]]:
    """Audit backend runtime dependencies. Everything here ships."""
    requirements = BACKEND / "requirements.txt"
    cmd = [
        sys.executable, "-m", "pip_audit",
        "--requirement", str(requirements),
        "--format", "json",
        "--progress-spinner", "off",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not result.stdout.strip():
        print("  pip-audit produced no output; treating as COULD NOT MEASURE")
        print(result.stderr[:500])
        return 1, []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("  pip-audit output was not JSON; treating as COULD NOT MEASURE")
        print(result.stdout[:400])
        return 1, []

    findings = []
    for dep in payload.get("dependencies", []):
        for vuln in dep.get("vulns", []) or []:
            findings.append({
                "package": dep.get("name"),
                "version": dep.get("version"),
                "id": vuln.get("id"),
                "fix": ", ".join(vuln.get("fix_versions") or []) or "none published",
            })
    return 0, findings


def run_npm_audit(production_only: bool) -> tuple[int, dict]:
    npm = find_npm()
    if npm is None:
        print("  npm not found; cannot audit frontend dependencies")
        return 1, {}

    cmd = [npm, "audit", "--json"]
    if production_only:
        cmd.append("--omit=dev")
    env = os.environ.copy()
    env["PATH"] = str(Path(npm).parent) + os.pathsep + env.get("PATH", "")
    # npm audit exits non-zero when it finds anything, so the exit code says
    # nothing useful here; the JSON body is what matters.
    result = subprocess.run(
        cmd, cwd=str(FRONTEND), capture_output=True, text=True, env=env
    )
    text = result.stdout.strip()
    if not text:
        print("  npm audit produced no output; treating as COULD NOT MEASURE")
        return 1, {}
    # npm sometimes prefixes warnings; take the JSON object.
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        print("  npm audit output was not JSON; treating as COULD NOT MEASURE")
        return 1, {}
    return 0, json.loads(match.group(0))


def summarise(vulns: dict) -> list[dict]:
    rows = []
    for name, v in vulns.items():
        titles = [
            via.get("title") for via in v.get("via", []) if isinstance(via, dict)
        ]
        rows.append({
            "package": name,
            "severity": v.get("severity", "unknown"),
            "range": v.get("range", "?"),
            "direct": v.get("isDirect", False),
            "titles": [t for t in titles if t],
        })
    rows.sort(key=lambda r: SEVERITY_ORDER.index(r["severity"])
              if r["severity"] in SEVERITY_ORDER else 99)
    return rows


def print_rows(rows: list[dict]) -> None:
    for r in rows:
        print(f"    {r['severity'].upper():<9} {r['package']:<22} {r['range']}")
        for title in r["titles"][:2]:
            print(f"      - {title[:96]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="development-only findings also fail the gate")
    args = parser.parse_args()

    print("Dependency vulnerability gate")
    print("=" * 74)
    failures = 0
    unmeasured = 0

    print("\nBackend runtime dependencies (pip-audit)")
    code, py_findings = run_pip_audit()
    if code != 0:
        unmeasured += 1
    elif py_findings:
        for f in py_findings:
            print(f"    {f['package']} {f['version']}: {f['id']} (fix: {f['fix']})")
        print(f"  FAIL: {len(py_findings)} vulnerability/ies in shipped Python packages")
        failures += 1
    else:
        print("  PASS: no known vulnerabilities")

    print("\nFrontend runtime dependencies (npm audit --omit=dev)")
    code, prod = run_npm_audit(production_only=True)
    prod_rows = summarise(prod.get("vulnerabilities", {})) if code == 0 else []
    if code != 0:
        unmeasured += 1
    elif prod_rows:
        print_rows(prod_rows)
        print(f"  FAIL: {len(prod_rows)} vulnerable package(s) reach the browser")
        failures += 1
    else:
        print("  PASS: no known vulnerabilities in shipped packages")

    print("\nFrontend development dependencies (npm audit, full tree)")
    code, full = run_npm_audit(production_only=False)
    if code != 0:
        unmeasured += 1
        dev_rows = []
    else:
        prod_names = {r["package"] for r in prod_rows}
        dev_rows = [r for r in summarise(full.get("vulnerabilities", {}))
                    if r["package"] not in prod_names]
        if dev_rows:
            print_rows(dev_rows)
            verdict = "FAIL" if args.strict else "REPORTED, does not fail the gate"
            print(f"  {verdict}: {len(dev_rows)} development-only package(s)")
            print("    These run on a developer machine and are not shipped.")
            if args.strict:
                failures += 1
        else:
            print("  PASS: no known vulnerabilities")

    print("\n" + "=" * 74)
    if unmeasured:
        print(f"COULD NOT MEASURE {unmeasured} check(s) -- treated as failure, "
              "because an unmeasured gate is not a passed gate.")
        return 1
    if failures:
        print(f"GATE FAILED: {failures} category/ies with shipped vulnerabilities.")
        return 1
    print("GATE PASSED: no vulnerabilities in anything that ships.")
    if dev_rows:
        print(f"({len(dev_rows)} development-only finding(s) reported above.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
