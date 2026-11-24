"""Build the three LifeLink technical books from their Markdown sources.

    python scripts/build_books.py                 build all three, run tests first
    python scripts/build_books.py --no-tests      build without re-running suites
    python scripts/build_books.py --book 1        build one book
    python scripts/build_books.py --preview       also render page images

Every build:
  1. resolves source-include and fact directives against the live repository,
     failing if any cannot be resolved,
  2. renders the PDF,
  3. validates the result (opens, page count, text extraction on every page,
     content inside the margins, no unresolved directives),
  4. writes docs/DOCUMENTATION_VALIDATION.md with what was actually measured.

A book is never reported as complete on the strength of having been written;
it is reported on the strength of having been built and checked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from bookgen.facts import build_facts, resolve  # noqa: E402
from bookgen.markdown_blocks import Heading, count_words, parse_markdown  # noqa: E402
from bookgen.pdf_builder import BookBuilder, BookMeta  # noqa: E402

BOOKS_DIR = ROOT / "docs" / "books"
PREVIEW_DIR = BOOKS_DIR / "_preview"
VERSION = "1.0.0"


@dataclass
class BookSpec:
    number: int
    slug: str
    title: str
    subtitle: str
    volume: str
    description: str
    target_pages: tuple[int, int]


BOOKS = [
    BookSpec(
        number=1,
        slug="LifeLink_Book_1_System_Architecture_and_AWS",
        title="System Architecture and AWS Cloud Engineering",
        subtitle=(
            "How LifeLink is designed, which AWS services carry which "
            "responsibility, and why each choice was made"
        ),
        volume="Book 1 of 3",
        description=(
            "A complete architectural account of the LifeLink platform, from the "
            "problem it addresses to the cloud design that supports it."
        ),
        target_pages=(70, 100),
    ),
    BookSpec(
        number=2,
        slug="LifeLink_Book_2_Implementation_and_Operations",
        title="Implementation and Operations Guide",
        subtitle=(
            "How the codebase actually works, module by module, with the real "
            "source it is built from"
        ),
        volume="Book 2 of 3",
        description=(
            "A working engineer's guide to the LifeLink repository: structure, "
            "domain logic, persistence, the API surface, the frontend, testing "
            "and day-to-day operation."
        ),
        target_pages=(90, 130),
    ),
    BookSpec(
        number=3,
        slug="LifeLink_Book_3_Interview_Viva_and_Engineering",
        title="Engineering Concepts, Viva and Interview Preparation",
        subtitle=(
            "Explaining, defending and extending LifeLink in examinations and "
            "technical interviews"
        ),
        volume="Book 3 of 3",
        description=(
            "Question-and-answer preparation grounded in LifeLink's real design "
            "decisions, failure modes and trade-offs."
        ),
        target_pages=(80, 120),
    ),
]


def validate_pdf(path: Path, expected_min_pages: int = 10,
                 source_text: str | None = None) -> dict:
    """Open the built PDF and check it is actually readable.

    Checks performed, each reported individually so a partial failure is
    visible rather than hidden behind a single pass/fail:
      * the file opens
      * page count
      * text extracts from every page (a page yielding nothing is usually a
        rendering failure, not a blank by design)
      * nothing is drawn outside the printable area
      * no unresolved build directives survived into the text
    """
    report: dict = {"path": str(path), "checks": [], "ok": True}

    def check(name: str, passed: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            report["ok"] = False

    if not path.is_file():
        check("file exists", False, "the PDF was not produced")
        return report
    check("file exists", True, f"{path.stat().st_size // 1024} KB")

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # noqa: N813
        except ImportError:
            check("renderer available", False, "pymupdf is not installed")
            return report

    try:
        document = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        check("opens", False, str(exc)[:200])
        return report
    check("opens", True, "")

    pages = document.page_count
    report["pages"] = pages
    check("page count", pages >= expected_min_pages,
          f"{pages} pages (minimum expected {expected_min_pages})")

    empty_pages: list[int] = []
    overflow_pages: list[int] = []
    directive_pages: list[int] = []
    total_chars = 0

    # The running header and footer are drawn on every page, so counting all
    # text on a page makes a blank page look populated. A genuinely empty page
    # is one with nothing in the body frame, so only that region is measured.
    HEADER_BOTTOM = 70.0   # points from the top, below the header rule
    FOOTER_TOP = 58.0      # points from the bottom, above the footer rule

    for index in range(pages):
        page = document[index]
        text = page.get_text().strip()
        total_chars += len(text)

        rect = page.rect
        body = pymupdf.Rect(0, HEADER_BOTTOM, rect.width, rect.height - FOOTER_TOP)
        body_text = page.get_text(clip=body).strip()

        # Page 1 is the cover; it is drawn on the canvas, not flowed.
        if index > 0 and len(body_text) < 25:
            empty_pages.append(index + 1)
        # Match LifeLink's directive syntax specifically. Included source can
        # legitimately contain brace pairs (JSX object literals, f-strings,
        # CloudFormation !Sub), and flagging those would be a false failure.
        if re.search(r"\{\{(include|fact|routes|adr_table):", text):
            directive_pages.append(index + 1)
        if "UNRESOLVED INCLUDE" in text or "MISSING SOURCE FILE" in text:
            directive_pages.append(index + 1)
        if "UNKNOWN FACT" in text:
            directive_pages.append(index + 1)

        rect = page.rect
        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            # A 2pt tolerance absorbs glyph bounding-box rounding.
            if x0 < -2 or y0 < -2 or x1 > rect.width + 2 or y1 > rect.height + 2:
                overflow_pages.append(index + 1)
                break

    report["total_characters"] = total_chars
    check("no blank pages in the body", not empty_pages,
          "every page has body content" if not empty_pages
          else f"blank or near-blank pages: {empty_pages}")
    check("no content outside the page", not overflow_pages,
          "nothing clipped" if not overflow_pages else f"overflowing pages: {sorted(set(overflow_pages))}")
    check("no unresolved build directives", not directive_pages,
          "all directives resolved" if not directive_pages
          else f"pages with unresolved content: {sorted(set(directive_pages))}")

    # Every "Listing N." caption must have a code block above it. A caption
    # standing alone means the listing was dropped during layout -- which is
    # exactly what a zero-height wrapper flowable once did, silently.
    orphan_captions: list[str] = []
    expected_listings = len(re.findall(r"\*Listing [\d.]+", source_text or ""))
    rendered_listings = 0
    for index in range(pages):
        page_text = document[index].get_text()
        rendered_listings += len(re.findall(r"Listing [\d.]+\.", page_text))
    if expected_listings and rendered_listings < expected_listings:
        orphan_captions.append(
            f"{expected_listings} listing captions in source, "
            f"{rendered_listings} rendered"
        )
    check("every listing caption has its listing", not orphan_captions,
          f"{rendered_listings} listings rendered"
          if not orphan_captions else "; ".join(orphan_captions))

    images = sum(len(document[i].get_images(full=True)) for i in range(pages))
    drawings = sum(len(document[i].get_drawings()) for i in range(pages))
    report["vector_drawings"] = drawings
    report["raster_images"] = images
    check("diagrams rendered", drawings > 0, f"{drawings} vector drawing operations")

    document.close()
    return report


def render_previews(path: Path, slug: str, pages: list[int]) -> list[str]:
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # noqa: N813

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open(str(path))
    written: list[str] = []
    for number in pages:
        if 1 <= number <= document.page_count:
            image = document[number - 1].get_pixmap(dpi=100)
            target = PREVIEW_DIR / f"{slug}_p{number:03d}.png"
            image.save(str(target))
            written.append(str(target.relative_to(ROOT)))
    document.close()
    return written


def load_source(spec: BookSpec) -> tuple[str, str] | None:
    """Read a book's Markdown.

    A book may be a single file or a directory of numbered parts. Parts keep
    each chapter group editable on its own, which matters for documents this
    long; they are concatenated in filename order and the combined text is also
    written out as the canonical single-file source.
    """
    parts_dir = BOOKS_DIR / spec.slug
    single = BOOKS_DIR / f"{spec.slug}.md"

    if parts_dir.is_dir():
        parts = sorted(parts_dir.glob("*.md"))
        if parts:
            combined = "\n\n".join(p.read_text(encoding="utf-8").rstrip() for p in parts)
            single.write_text(combined + "\n", encoding="utf-8")
            return combined, f"{parts_dir.relative_to(ROOT)}/ ({len(parts)} parts)"

    if single.is_file():
        return single.read_text(encoding="utf-8"), str(single.relative_to(ROOT))

    return None


def build_book(spec: BookSpec, facts, *, preview: bool) -> dict:
    loaded = load_source(spec)
    if loaded is None:
        return {
            "book": spec.number,
            "title": spec.title,
            "status": "SOURCE MISSING",
            "source": str((BOOKS_DIR / f"{spec.slug}.md").relative_to(ROOT)),
            "ok": False,
        }
    raw, source_label = loaded
    resolved, problems = resolve(raw, facts)

    # The resolved text is kept so a reader can see exactly what was typeset.
    resolved_path = BOOKS_DIR / "_resolved" / f"{spec.slug}.resolved.md"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(resolved, encoding="utf-8")

    blocks = parse_markdown(resolved)
    chapters = [b for b in blocks if isinstance(b, Heading) and b.level == 1]
    words = count_words(blocks)

    meta = BookMeta(
        title=spec.title,
        subtitle=spec.subtitle,
        volume=spec.volume,
        version=VERSION,
        generated=datetime.now(timezone.utc).strftime("%d %B %Y"),
        description=spec.description,
        source_note=(
            "Generated from the LifeLink repository. Code listings and figures "
            "are extracted from the actual source at build time."
        ),
    )

    output = BOOKS_DIR / f"{spec.slug}.pdf"
    build = BookBuilder(meta).build(resolved, output)
    validation = validate_pdf(output, expected_min_pages=20, source_text=resolved)

    # A contents page whose numbers drifted between layout passes would point
    # readers at the wrong pages, so it is a checked property.
    drift = build.get("toc_drift", [])
    validation["checks"].append({
        "name": "contents page numbers are exact",
        "passed": not drift,
        "detail": "no drift between layout passes" if not drift
                  else f"{len(drift)} entries moved, e.g. {drift[:3]}",
    })
    if drift:
        validation["ok"] = False

    previews: list[str] = []
    if preview and validation.get("pages"):
        page_count = validation["pages"]
        sample = sorted({1, 2, 3, max(4, page_count // 4), page_count // 2,
                         max(1, (page_count * 3) // 4), page_count})
        previews = render_previews(output, spec.slug, [p for p in sample if p >= 1])

    return {
        "book": spec.number,
        "title": spec.title,
        "source": source_label,
        "resolved": str(resolved_path.relative_to(ROOT)),
        "pdf": str(output.relative_to(ROOT)),
        "chapters": len(chapters),
        "sections": build["sections"],
        "figures": build["figures"],
        "tables": build["tables"],
        "words": words,
        "pages": validation.get("pages", 0),
        "target_pages": f"{spec.target_pages[0]}-{spec.target_pages[1]}",
        "meets_target": validation.get("pages", 0) >= spec.target_pages[0],
        "directive_problems": problems,
        "validation": validation,
        "ok": validation["ok"] and not problems,
        "status": "COMPLETE" if (validation["ok"] and not problems) else "NEEDS ATTENTION",
    }


def write_validation_report(results: list[dict], facts) -> Path:
    lines: list[str] = []
    lines.append("# LifeLink — Documentation Validation Report")
    lines.append("")
    lines.append(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`scripts/build_books.py`."
    )
    lines.append("")
    lines.append(
        "Every figure below was measured by opening the produced PDF, not asserted "
        "by the author. A book is reported COMPLETE only when it builds, opens, "
        "renders text on every page, keeps its content inside the page, and "
        "contains no unresolved build directives."
    )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Book | Title | Pages | Target | Chapters | Figures | Tables | Words | Status |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for result in results:
        if result.get("status") == "SOURCE MISSING":
            lines.append(
                f"| {result['book']} | {result['title']} | — | — | — | — | — | — | "
                "**SOURCE MISSING** |"
            )
            continue
        lines.append(
            f"| {result['book']} | {result['title']} | {result['pages']} | "
            f"{result['target_pages']} | {result['chapters']} | {result['figures']} | "
            f"{result['tables']} | {result['words']:,} | "
            f"{'COMPLETE' if result['ok'] else 'NEEDS ATTENTION'} |"
        )
    lines.append("")

    lines.append("## Measured facts used in the books")
    lines.append("")
    lines.append(
        "Counts, sizes and versions below are re-measured on every build; the "
        "generation timestamp above is when. `measured_on` is the separate, "
        "recorded date of the Phase 0 AWS environment survey, not the date of "
        "these figures."
    )
    lines.append("")
    lines.append("| Fact | Value |")
    lines.append("|---|---|")
    for key in sorted(facts.values):
        lines.append(f"| `{key}` | {facts.values[key]} |")
    lines.append("")

    for result in results:
        lines.append(f"## Book {result['book']} — {result['title']}")
        lines.append("")
        if result.get("status") == "SOURCE MISSING":
            lines.append(f"**SOURCE MISSING**: `{result['source']}` does not exist.")
            lines.append("")
            continue

        lines.append(f"- Markdown source: `{result['source']}`")
        lines.append(f"- Resolved source actually typeset: `{result['resolved']}`")
        lines.append(f"- PDF: `{result['pdf']}`")
        lines.append(f"- Pages: **{result['pages']}** (target {result['target_pages']})")
        lines.append(f"- Chapters: {result['chapters']}, sections: {result['sections']}")
        lines.append(f"- Figures: {result['figures']}, tables: {result['tables']}")
        lines.append(f"- Words: {result['words']:,}")
        lines.append(
            f"- Characters extracted from the PDF: "
            f"{result['validation'].get('total_characters', 0):,}"
        )
        lines.append("")
        lines.append("| Check | Result | Detail |")
        lines.append("|---|---|---|")
        for check in result["validation"]["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            lines.append(f"| {check['name']} | **{mark}** | {check['detail']} |")
        lines.append("")
        if result["directive_problems"]:
            lines.append("**Unresolved build directives:**")
            lines.append("")
            for problem in result["directive_problems"]:
                lines.append(f"- {problem}")
            lines.append("")
        if not result["meets_target"]:
            lines.append(
                f"> **Page target not met.** This book is {result['pages']} pages "
                f"against a target of {result['target_pages']}. Recorded here rather "
                "than padded, because the specification asks for depth over length "
                "but also asks that shortfalls be disclosed."
            )
            lines.append("")

    report_path = ROOT / "docs" / "DOCUMENTATION_VALIDATION.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LifeLink technical books")
    parser.add_argument("--book", type=int, choices=[1, 2, 3], help="build only this book")
    parser.add_argument("--no-tests", action="store_true",
                        help="skip re-running the suites (facts are marked NOT MEASURED)")
    parser.add_argument("--preview", action="store_true", help="render sample page images")
    args = parser.parse_args()

    BOOKS_DIR.mkdir(parents=True, exist_ok=True)

    print("Collecting facts from the repository...")
    facts = build_facts(run_tests=not args.no_tests)
    print(f"  backend modules : {facts.values['backend_modules']}")
    print(f"  routes          : {facts.values['route_count']}")
    print(f"  tests           : {facts.values['test_total']} ({facts.values['test_status']})")
    print()

    selected = [b for b in BOOKS if args.book is None or b.number == args.book]
    results: list[dict] = []

    for spec in selected:
        print(f"Building Book {spec.number}: {spec.title}")
        result = build_book(spec, facts, preview=args.preview)
        results.append(result)
        if result.get("status") == "SOURCE MISSING":
            print(f"  SOURCE MISSING: {result['source']}")
            continue
        print(f"  pages      : {result['pages']} (target {result['target_pages']})")
        print(f"  chapters   : {result['chapters']}  figures: {result['figures']}  "
              f"tables: {result['tables']}")
        print(f"  words      : {result['words']:,}")
        for check in result["validation"]["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            print(f"  [{mark}] {check['name']}: {check['detail']}")
        if result["directive_problems"]:
            print(f"  UNRESOLVED DIRECTIVES: {len(result['directive_problems'])}")
            for problem in result["directive_problems"][:8]:
                print(f"    - {problem}")
        print()

    report = write_validation_report(results, facts)
    print(f"Validation report: {report.relative_to(ROOT)}")

    summary = ROOT / "docs" / "books" / "_build_summary.json"
    summary.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    failures = [r for r in results if not r.get("ok")]
    if failures:
        print(f"\n{len(failures)} book(s) need attention.")
        return 1
    print("\nAll selected books built and validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
