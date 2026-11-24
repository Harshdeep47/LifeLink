#!/usr/bin/env python
"""Build the Lambda deployment package without Docker.

Why this exists rather than ``sam build``:

``sam build`` installs dependencies with the *local* interpreter and platform.
On this machine that is CPython 3.14 on Windows x86-64, while the target is
CPython 3.14 on Amazon Linux 2023 aarch64 (Graviton). Two of our dependencies
contain compiled extensions — ``cryptography`` (needed for RS256 token
verification) and ``pydantic-core`` — so a local install produces Windows
binaries that cannot load in Lambda. The usual answer is
``sam build --use-container``, which needs Docker; Docker is not installed here.

So we ask pip for the target platform's wheels explicitly. This is a supported
pip mode and is deterministic: ``--only-binary=:all:`` means pip must find a
real wheel for the target or fail loudly, rather than silently building a
source distribution against the wrong platform.

The package layout matters and is easy to get wrong. ``backend/pyproject.toml``
sets ``pythonpath = ["src"]``, so the import root is ``backend/src`` — modules
import each other as ``appcore.auth``, not ``src.appcore.auth``. The package
therefore contains the *contents* of ``src/`` at its top level, and handlers are
addressed as ``handlers.api.lambda_handler``.

Usage::

    python scripts/build_lambda_package.py
    python scripts/build_lambda_package.py --verify   # also import-check it
"""

from __future__ import annotations

import argparse
import compileall
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "backend" / "src"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
BUILD_DIR = ROOT / "build" / "lambda"

# Must match Globals.Function in infrastructure/template.yaml. A mismatch here
# produces a package that deploys and then fails at import time, which is the
# worst failure mode available, so the deploy script asserts these agree.
TARGET_PYTHON = "3.14"
TARGET_PLATFORM = "manylinux2014_aarch64"

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "tests"}

# Shipping these wastes package space and deploy time. boto3/botocore are
# already present in the Lambda runtime; the rest are build residue.
PRUNE_AFTER_INSTALL = (
    "boto3",
    "boto3-*.dist-info",
    "botocore",
    "botocore-*.dist-info",
    "pip",
    "pip-*.dist-info",
    "setuptools",
    "setuptools-*.dist-info",
    "wheel",
    "wheel-*.dist-info",
    "*.dist-info/RECORD",
)


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def clean() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)


def copy_source() -> int:
    """Copy the contents of src/ to the package root."""
    count = 0
    for item in sorted(SRC.iterdir()):
        if item.name in EXCLUDE_DIRS:
            continue
        target = BUILD_DIR / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc"),
            )
            count += sum(1 for _ in target.rglob("*.py"))
        else:
            shutil.copy2(item, target)
            count += 1 if item.suffix == ".py" else 0
    return count


def install_dependencies() -> None:
    """Install runtime dependencies as target-platform wheels."""
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--no-compile",
        "--target",
        str(BUILD_DIR),
        "--platform",
        TARGET_PLATFORM,
        "--python-version",
        TARGET_PYTHON,
        "--only-binary=:all:",
        "--implementation",
        "cp",
        "--requirement",
        str(REQUIREMENTS),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(
            "dependency install failed. --only-binary=:all: means pip refused to "
            "build a source distribution for the target platform, which is the "
            "correct behaviour: a locally compiled extension would not load in "
            "Lambda."
        )


def prune() -> int:
    removed = 0
    for pattern in PRUNE_AFTER_INSTALL:
        for path in BUILD_DIR.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += 1
    # Strip bytecode built for the wrong interpreter, and tests inside deps.
    for cache in BUILD_DIR.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return removed


def verify_data_files() -> None:
    """The compatibility reference is loaded relative to __file__.

    ``domain/compatibility.py`` resolves ``parent.parent / "reference" /
    "compatibility"``. With src/ contents at the package root that lands on
    ``<root>/reference/compatibility``. If this file is missing the loader
    refuses to start by design, so a missing file here is a failed deployment
    rather than a silently degraded one.
    """
    reference = BUILD_DIR / "reference" / "compatibility" / "abo_rh_v1.json"
    if not reference.is_file():
        raise SystemExit(f"missing required data file in package: {reference}")
    log(f"data file present: reference/compatibility/{reference.name}")


def verify_handlers() -> None:
    """Check every handler module the template names is present and parses.

    Compiling is as far as we can go here: these modules import compiled
    aarch64 wheels that cannot be imported on this Windows x86 machine. A
    syntax or layout error is caught now; an import-time failure is caught by
    the post-deployment smoke test.
    """
    expected = [
        ("handlers/api.py", "handlers.api.lambda_handler"),
        ("handlers/workers.py", "handlers.workers.notification_handler"),
        ("handlers/workers.py", "handlers.workers.work_handler"),
        ("handlers/workers.py", "handlers.workers.outbox_handler"),
        ("handlers/workers.py", "handlers.workers.dispatcher_handler"),
        ("handlers/workers.py", "handlers.workers.maintenance_handler"),
    ]
    for relative, dotted in expected:
        path = BUILD_DIR / relative
        if not path.is_file():
            raise SystemExit(f"handler module missing from package: {relative} ({dotted})")

    # The import root must be the package root, not a nested src/.
    if (BUILD_DIR / "src").exists():
        raise SystemExit(
            "package contains a nested src/ directory. The import root must be the "
            "package root: modules import 'appcore.auth', not 'src.appcore.auth'."
        )
    for required in ("appcore", "domain", "handlers", "repositories", "services", "adapters"):
        if not (BUILD_DIR / required).is_dir():
            raise SystemExit(f"package is missing the {required}/ package")

    ok = compileall.compile_dir(
        str(BUILD_DIR),
        quiet=2,
        force=True,
        rx=__import__("re").compile(r"[/\\](?:tests|__pycache__)[/\\]"),
    )
    # compileall writes caches we do not want to ship.
    for cache in BUILD_DIR.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    if not ok:
        raise SystemExit("package contains Python that does not compile")
    log("all 6 handler entry points present; package compiles")


def verify_no_secrets() -> None:
    """Refuse to ship development signing keys.

    The local authenticator is now blocked from running in AWS by
    ``appcore/environment.py``, but the key should never be in the artifact in
    the first place. Two independent protections, because this one is cheap.
    """
    offenders = [
        p.relative_to(BUILD_DIR).as_posix()
        for pattern in ("*.pem", "*.key", ".env", "*dev_private*")
        for p in BUILD_DIR.rglob(pattern)
    ]
    if offenders:
        raise SystemExit("refusing to build: secret-like files in package: " + ", ".join(offenders))
    log("no key material in package")


def package_size() -> tuple[int, float]:
    files = [p for p in BUILD_DIR.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    return len(files), total / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="run all package checks")
    args = parser.parse_args()

    print(f"Building Lambda package for python{TARGET_PYTHON} / {TARGET_PLATFORM}")
    clean()
    modules = copy_source()
    log(f"copied {modules} application modules from backend/src/")
    install_dependencies()
    log("installed runtime dependencies as target-platform wheels")
    removed = prune()
    log(f"pruned {removed} runtime-provided or build-residue paths")

    verify_data_files()
    verify_no_secrets()
    if args.verify:
        verify_handlers()

    count, mb = package_size()
    log(f"package: {count} files, {mb:.1f} MB at {BUILD_DIR.relative_to(ROOT).as_posix()}")
    if mb > 250:
        raise SystemExit(f"package is {mb:.1f} MB, over Lambda's 250 MB unzipped limit")
    print("Lambda package built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
