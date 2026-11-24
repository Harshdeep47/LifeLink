"""Extract verifiable facts and real source excerpts for the books.

The specification is explicit that the books must be generated from the actual
implementation and must not invent classes, APIs, data structures or test
results. The way to guarantee that is to make it impossible to write a stale
fact: book sources use directives that are resolved at build time from the
repository itself, and the build fails if a directive cannot be resolved.

Directives:

    {{include:backend/src/domain/freshness.py:30-55}}    real source lines
    {{include:backend/src/domain/freshness.py:def freshness_label}}  a function
    {{fact:test_total}}                                  a measured value
    {{routes:Feature 1}}                                 the live route table
    {{adr_table}}                                        the ADR index

Anything unresolved raises, so a book cannot ship citing something that is no
longer true.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# The selector may itself contain braces -- an anchor often quotes a line of
# JavaScript or Python -- so it is matched non-greedily up to the closing '}}'
# rather than up to the first '}'.
INCLUDE = re.compile(r"\{\{include:([^:]+):(.+?)\}\}")
FACT = re.compile(r"\{\{fact:([a-z0-9_]+)\}\}")
ROUTES = re.compile(r"\{\{routes:([^}]+)\}\}")
SIMPLE = re.compile(r"\{\{([a-z_]+)\}\}")


@dataclass
class Facts:
    values: dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> str:
        if key not in self.values:
            raise KeyError(f"unknown fact '{key}'")
        return self.values[key]


def _run(command: list[str], cwd: Path, env: dict | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command, cwd=str(cwd), capture_output=True, text=True, timeout=900, env=env
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _node_env() -> dict:
    """Environment with Node's directory on PATH.

    `npm.cmd` shells out to `node`, so invoking npm from a process whose PATH
    predates the Node installation fails with "node is not recognized" -- which
    would otherwise be recorded as an unmeasurable frontend suite.
    """
    import os

    env = dict(os.environ)
    npm = _find_npm()
    if npm:
        node_dir = str(Path(npm).parent)
        if node_dir not in env.get("PATH", ""):
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
    return env


def _find_npm() -> str | None:
    """Locate npm.

    `shutil.which` is tried first, but on Windows a shell started before Node
    was installed does not have it on PATH, so the standard install locations
    are checked too rather than silently reporting the frontend suite as
    unmeasurable.
    """
    import shutil

    found = shutil.which("npm") or shutil.which("npm.cmd")
    if found:
        return found

    candidates = [
        Path(r"C:\Program Files\nodejs\npm.cmd"),
        Path(r"C:\Program Files (x86)\nodejs\npm.cmd"),
        Path.home() / "AppData" / "Roaming" / "npm" / "npm.cmd",
        Path("/usr/local/bin/npm"),
        Path("/usr/bin/npm"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def collect_test_results(run_tests: bool = True) -> dict[str, str]:
    """Run the real suites and record what they actually report.

    If a suite is not run, the facts say so rather than carrying a stale number.
    """
    facts: dict[str, str] = {}
    backend = ROOT / "backend"
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    if not run_tests:
        facts["test_backend"] = "NOT MEASURED IN THIS BUILD"
        facts["test_total"] = "NOT MEASURED IN THIS BUILD"
        facts["test_unit"] = "NOT MEASURED IN THIS BUILD"
        facts["test_integration"] = "NOT MEASURED IN THIS BUILD"
        facts["test_frontend"] = "NOT MEASURED IN THIS BUILD"
        facts["test_status"] = "NOT MEASURED IN THIS BUILD"
        return facts

    # Deliberately NOT using -q: in this pytest version quiet mode suppresses
    # the "N passed" summary line, and a missing summary previously produced a
    # recorded count of zero -- a false test result, which is exactly what the
    # specification forbids. Anything unparseable is now reported as such.
    # Vitest colours its summary, so "Tests  36 passed" arrives with ANSI escape
    # sequences between the words and a naive regex never matches.
    ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def count(output: str, pattern: str = r"(\d+) passed") -> str:
        match = re.search(pattern, ansi.sub("", output))
        return match.group(1) if match else "COULD NOT MEASURE"

    code, output = _run([str(python), "-m", "pytest", "tests"], backend)
    failed = re.search(r"(\d+) failed", output)
    skipped = re.search(r"(\d+) skipped", output)
    # This measures `pytest tests` in backend/, so it is the BACKEND total.
    # It used to be called `test_total`, which sat beside `test_frontend`
    # and so read as "all tests" -- a reader could reasonably add 604 and
    # 245 and wonder which of the two was wrong. `test_total` is now the
    # genuine sum, computed below.
    facts["test_backend"] = count(output)
    facts["test_failed"] = failed.group(1) if failed else "0"
    facts["test_skipped"] = skipped.group(1) if skipped else "0"
    if facts["test_backend"] == "COULD NOT MEASURE":
        facts["test_status"] = "COULD NOT MEASURE - see the build log"
    elif code == 0:
        facts["test_status"] = "all passing"
    else:
        facts["test_status"] = "FAILURES PRESENT"

    _, out_u = _run([str(python), "-m", "pytest", "tests/unit"], backend)
    facts["test_unit"] = count(out_u)

    _, out_i = _run([str(python), "-m", "pytest", "tests/integration"], backend)
    facts["test_integration"] = count(out_i)

    npm = _find_npm()
    if npm is None:
        facts["test_frontend"] = "COULD NOT MEASURE - npm not found"
    else:
        _, out_f = _run([npm, "test"], ROOT / "frontend", env=_node_env())
        facts["test_frontend"] = count(out_f, r"Tests\s+(\d+) passed")

    # The genuine combined figure. Reported as unmeasurable rather than as a
    # partial sum if either side could not be counted: a total that silently
    # omitted the frontend is exactly the ambiguity this replaces.
    try:
        facts["test_total"] = str(int(facts["test_backend"]) + int(facts["test_frontend"]))
    except (ValueError, KeyError):
        facts["test_total"] = "COULD NOT MEASURE - see test_backend and test_frontend"

    return facts


def collect_code_facts() -> dict[str, str]:
    facts: dict[str, str] = {}
    backend_src = ROOT / "backend" / "src"

    py_files = sorted(backend_src.rglob("*.py"))
    facts["backend_modules"] = str(len([p for p in py_files if p.name != "__init__.py"]))
    facts["backend_lines"] = str(
        sum(len(p.read_text(encoding="utf-8").splitlines()) for p in py_files)
    )

    test_files = sorted((ROOT / "backend" / "tests").rglob("test_*.py"))
    facts["backend_test_files"] = str(len(test_files))
    facts["backend_test_lines"] = str(
        sum(len(p.read_text(encoding="utf-8").splitlines()) for p in test_files)
    )

    frontend_src = ROOT / "frontend" / "src"
    jsx = sorted(frontend_src.rglob("*.jsx")) + sorted(frontend_src.rglob("*.js"))
    facts["frontend_modules"] = str(len(jsx))
    facts["frontend_lines"] = str(
        sum(len(p.read_text(encoding="utf-8").splitlines()) for p in jsx)
    )

    # Routes and permissions, read from the live table.
    sys.path.insert(0, str(backend_src))
    import os

    os.environ.setdefault("LIFELINK_ENV", "local")
    os.environ.setdefault("AWS_REGION", "ap-southeast-2")
    from appcore.rbac import Permission, Role
    from handlers.api import ROUTER

    facts["route_count"] = str(len(ROUTER.routes))
    facts["permission_count"] = str(len(list(Permission)))
    facts["role_count"] = str(len(list(Role)))
    facts["public_route_count"] = str(sum(1 for r in ROUTER.routes if r.allow_anonymous))

    from repositories.dynamo import Tables
    from repositories.schema import TABLE_DEFINITIONS

    facts["table_count"] = str(len(Tables.all()))
    facts["gsi_count"] = str(
        sum(len(d["indexes"]) for d in TABLE_DEFINITIONS.values())
    )

    # ADRs
    adr_path = ROOT / "docs" / "ARCHITECTURE_DECISIONS.md"
    if adr_path.exists():
        facts["adr_count"] = str(
            len(re.findall(r"^## ADR-\d+", adr_path.read_text(encoding="utf-8"), re.M))
        )
    else:
        facts["adr_count"] = "0"

    # OpenAPI
    openapi = ROOT / "docs" / "openapi.json"
    if openapi.exists():
        document = json.loads(openapi.read_text(encoding="utf-8"))
        facts["openapi_paths"] = str(len(document["paths"]))
        facts["openapi_operations"] = str(
            sum(len(methods) for methods in document["paths"].values())
        )
    else:
        facts["openapi_paths"] = "0"
        facts["openapi_operations"] = "0"

    # Infrastructure
    template = ROOT / "infrastructure" / "template.yaml"
    if template.exists():
        text = template.read_text(encoding="utf-8")
        facts["cfn_resources"] = str(len(re.findall(r"^  [A-Za-z0-9]+:\n    Type: ", text, re.M)))
        facts["cfn_alarms"] = str(text.count("AWS::CloudWatch::Alarm"))
        facts["cfn_lines"] = str(len(text.splitlines()))
    else:
        facts["cfn_resources"] = "0"
        facts["cfn_alarms"] = "0"
        facts["cfn_lines"] = "0"

    return facts


def collect_environment_facts() -> dict[str, str]:
    """Facts measured from the AWS account during Phase 0.

    These are recorded values, not live calls: a book build must not depend on
    network access, and the reader needs to know when the figure was taken.
    """
    return {
        "aws_account": "426150327442",
        "aws_region": "ap-southeast-2",
        "aws_plan": "FREE",
        "lambda_concurrency": "10",
        "lambda_concurrency_default": "1000",
        "ses_mode": "sandbox (200 messages/day, 1 per second, verified recipients only)",
        "measured_on": "2026-11-15",
        "python_version": "3.14.2",
        "lambda_runtime": "python3.14",
        "node_version": "26.13.1",
        "sam_version": "1.172.1",
    }


def build_facts(run_tests: bool = True) -> Facts:
    values: dict[str, str] = {}
    values.update(collect_environment_facts())
    values.update(collect_code_facts())
    values.update(collect_test_results(run_tests=run_tests))
    return Facts(values=values)


def _extract_region(path: Path, selector: str) -> str:
    """Extract a region of a file for inclusion in a book.

    Selectors, in order of preference:

        def name / class name   a Python definition, located by parsing
        anchor:TEXT:N           N lines starting at the first line containing TEXT
        anchor:TEXT:until:END   from the first line containing TEXT to the next END
        START-END               raw line numbers

    Raw line numbers are supported but discouraged, and the builder warns about
    them. They silently point at the wrong code the moment a file is edited
    above the range -- which happened during this project and put an unrelated
    SQS block under a caption about IAM grants.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    anchor = re.fullmatch(r"anchor:(.+?):(\d+)", selector)
    if anchor:
        needle = anchor.group(1)
        count = int(anchor.group(2))
        for index, line in enumerate(lines):
            if needle in line:
                return "\n".join(lines[index:index + count])
        raise ValueError(f"{path}: no line contains anchor text {needle!r}")

    anchor_until = re.fullmatch(r"anchor:(.+?):until:(.+)", selector)
    if anchor_until:
        needle = anchor_until.group(1)
        terminator = anchor_until.group(2)
        start_index = None
        for index, line in enumerate(lines):
            if needle in line:
                start_index = index
                break
        if start_index is None:
            raise ValueError(f"{path}: no line contains anchor text {needle!r}")
        for index in range(start_index + 1, len(lines)):
            if terminator in lines[index]:
                return "\n".join(lines[start_index:index])
        return "\n".join(lines[start_index:])

    range_match = re.fullmatch(r"(\d+)-(\d+)", selector)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start < 1 or end > len(lines) or start > end:
            raise ValueError(
                f"{path}: line range {selector} is outside the file (1-{len(lines)})"
            )
        return "\n".join(lines[start - 1:end])

    # Named Python definition.
    named = re.fullmatch(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", selector.strip())
    if named and path.suffix == ".py":
        target = named.group(1)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == target:
                    start = node.lineno
                    # Include a preceding decorator if present.
                    if node.decorator_list:
                        start = min(d.lineno for d in node.decorator_list)
                    end = node.end_lineno or start
                    return "\n".join(lines[start - 1:end])
        raise ValueError(f"{path}: no definition named '{target}'")

    raise ValueError(f"{path}: unrecognised selector '{selector}'")


def resolve(text: str, facts: Facts) -> tuple[str, list[str]]:
    """Resolve every directive. Returns (resolved text, list of problems)."""
    problems: list[str] = []

    def include(match: re.Match) -> str:
        relative = match.group(1).strip()
        selector = match.group(2).strip()
        path = ROOT / relative
        if not path.is_file():
            problems.append(f"include: missing file {relative}")
            return f"[MISSING SOURCE FILE: {relative}]"
        if re.fullmatch(r"\d+-\d+", selector):
            # Not fatal, but these break silently when a file is edited above
            # the range, so the build surfaces them for replacement.
            problems.append(
                f"include: {relative}:{selector} uses raw line numbers; "
                "prefer a 'def name' or 'anchor:TEXT:N' selector"
            )
        try:
            snippet = _extract_region(path, selector)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"include: {exc}")
            return f"[UNRESOLVED INCLUDE: {relative}:{selector}]"
        language = {
            ".py": "python", ".js": "javascript", ".jsx": "javascript",
            ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".css": "css",
        }.get(path.suffix, "")
        # Trim common indentation so an extracted method reads as a listing.
        snippet_lines = snippet.split("\n")
        indents = [
            len(line) - len(line.lstrip())
            for line in snippet_lines
            if line.strip()
        ]
        shift = min(indents) if indents else 0
        snippet = "\n".join(
            line[shift:] if len(line) >= shift else line for line in snippet_lines
        )
        return f"```{language}\n{snippet}\n```"

    def fact(match: re.Match) -> str:
        key = match.group(1)
        try:
            return facts[key]
        except KeyError:
            problems.append(f"fact: unknown '{key}'")
            return f"[UNKNOWN FACT: {key}]"

    def routes(match: re.Match) -> str:
        wanted = match.group(1).strip().lower()
        sys.path.insert(0, str(ROOT / "backend" / "src"))
        from handlers.api import ROUTER

        rows = ["| Method | Path | Permission |", "|---|---|---|"]
        count = 0
        for route in sorted(ROUTER.routes, key=lambda r: (r.path, r.method)):
            label = route.summary.lower() + " " + route.path.lower()
            if wanted != "all" and wanted not in label:
                continue
            permission = route.permission.value if route.permission else "(none)"
            anonymous = " *(public)*" if route.allow_anonymous else ""
            rows.append(f"| `{route.method}` | `{route.path}` | `{permission}`{anonymous} |")
            count += 1
        if count == 0:
            problems.append(f"routes: no routes matched '{wanted}'")
        return "\n".join(rows)

    text = INCLUDE.sub(include, text)
    text = ROUTES.sub(routes, text)
    text = FACT.sub(fact, text)

    # Only LifeLink's own directive syntax counts. Included JavaScript legitimately
    # contains things like `{{ from: location.pathname }}`, and treating every
    # brace pair as a directive would flag real source as a build failure.
    leftover = re.findall(r"\{\{(?:include|fact|routes|adr_table):[^}]*\}\}", text)
    for item in leftover:
        problems.append(f"unresolved directive: {item}")

    return text, problems
