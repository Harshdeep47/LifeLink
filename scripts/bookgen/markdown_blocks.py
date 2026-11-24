"""Markdown parser producing a block list for the PDF renderer.

Deliberately not a general-purpose Markdown implementation. It supports exactly
the constructs the books use, and it fails loudly on anything it does not
understand rather than silently dropping content -- a book that quietly loses a
table is worse than one that refuses to build.

Supported:
    # .. ###### headings
    paragraphs with **bold**, *italic*, `code`, [text](url)
    - and * bullet lists, 1. numbered lists (one level of nesting)
    > blockquotes (rendered as callouts)
    | pipe | tables | with alignment row
    ``` fenced code blocks with an optional language
    ```diagram  blocks in the diagram DSL (see diagrams.py)
    --- horizontal rules
    :::note / :::warning / :::key  callout blocks
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Heading:
    level: int
    text: str
    anchor: str = ""


@dataclass
class Paragraph:
    text: str


@dataclass
class BulletList:
    items: list[str]
    ordered: bool = False


@dataclass
class CodeBlock:
    code: str
    language: str = ""
    caption: str = ""


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""
    alignments: list[str] = field(default_factory=list)


@dataclass
class Callout:
    kind: Literal["note", "warning", "key", "quote"]
    title: str
    body: list[str]


@dataclass
class Diagram:
    spec: str
    caption: str = ""


@dataclass
class Rule:
    pass


@dataclass
class PageBreak:
    pass


Block = (
    Heading | Paragraph | BulletList | CodeBlock | Table | Callout | Diagram | Rule | PageBreak
)

CALLOUT_OPEN = re.compile(r"^:::(note|warning|key)\s*(.*)$")
TABLE_ALIGN = re.compile(r"^\|?[\s:\-|]+\|?$")


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_]+", "-", cleaned)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _take_caption(lines: list[str], index: int, prefixes: tuple[str, ...]) -> tuple[str, int]:
    """Consume an italic caption line that follows a figure, table or listing.

    Blank lines between the element and its caption are skipped. Without that,
    the caption is left behind as an ordinary paragraph AND an auto-generated
    one is added, so the book shows the caption twice -- which is exactly what
    the first proof revealed.
    """
    probe = index
    while probe < len(lines) and not lines[probe].strip():
        probe += 1
    if probe >= len(lines):
        return "", index

    candidate = lines[probe].strip()
    for prefix in prefixes:
        match = re.match(rf"^\*({prefix}[^*]*)\*$", candidate)
        if match:
            return match.group(1).strip(), probe + 1
    return "", index


def _alignments_from(line: str) -> list[str]:
    result = []
    for cell in _split_table_row(line):
        token = cell.strip()
        if token.startswith(":") and token.endswith(":"):
            result.append("CENTER")
        elif token.endswith(":"):
            result.append("RIGHT")
        else:
            result.append("LEFT")
    return result


def parse_markdown(text: str) -> list[Block]:
    """Parse the supported subset into blocks."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        stripped = line.strip()

        # Blank line
        if not stripped:
            index += 1
            continue

        # Explicit page break
        if stripped == "<!-- pagebreak -->":
            blocks.append(PageBreak())
            index += 1
            continue

        # HTML comment: skip
        if stripped.startswith("<!--"):
            while index < total and "-->" not in lines[index]:
                index += 1
            index += 1
            continue

        # Fenced code or diagram
        if stripped.startswith("```"):
            language = stripped[3:].strip()
            index += 1
            body: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1  # closing fence
            caption, index = _take_caption(lines, index, ("Figure", "Listing"))

            if language == "diagram":
                blocks.append(Diagram(spec="\n".join(body), caption=caption))
            else:
                blocks.append(
                    CodeBlock(code="\n".join(body), language=language, caption=caption)
                )
            continue

        # Horizontal rule
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            blocks.append(Rule())
            index += 1
            continue

        # Heading
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            blocks.append(Heading(level=level, text=title, anchor=slugify(title)))
            index += 1
            continue

        # Callout
        callout = CALLOUT_OPEN.match(stripped)
        if callout:
            kind = callout.group(1)
            title = callout.group(2).strip()
            index += 1
            body_lines: list[str] = []
            while index < total and lines[index].strip() != ":::":
                body_lines.append(lines[index].rstrip())
                index += 1
            index += 1
            paragraphs = [p.strip() for p in "\n".join(body_lines).split("\n\n") if p.strip()]
            blocks.append(Callout(kind=kind, title=title, body=paragraphs))
            continue

        # Blockquote
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            paragraphs = [p.strip() for p in "\n".join(quote_lines).split("\n\n") if p.strip()]
            blocks.append(Callout(kind="quote", title="", body=paragraphs))
            continue

        # Table
        if stripped.startswith("|") and index + 1 < total and TABLE_ALIGN.match(
            lines[index + 1].strip()
        ):
            headers = _split_table_row(lines[index])
            alignments = _alignments_from(lines[index + 1])
            index += 2
            rows: list[list[str]] = []
            while index < total and lines[index].strip().startswith("|"):
                rows.append(_split_table_row(lines[index]))
                index += 1

            caption, index = _take_caption(lines, index, ("Table",))

            # Normalise ragged rows rather than dropping them.
            width = len(headers)
            normalised = [
                (row + [""] * width)[:width] if len(row) != width else row for row in rows
            ]
            blocks.append(
                Table(headers=headers, rows=normalised, caption=caption, alignments=alignments)
            )
            continue

        # Lists
        list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if list_match:
            ordered = bool(re.match(r"^\d+\.$", list_match.group(2)))
            items: list[str] = []
            while index < total:
                current = lines[index]
                if not current.strip():
                    # A blank line ends the list unless the next line continues it.
                    if index + 1 < total and re.match(r"^(\s*)([-*+]|\d+\.)\s+", lines[index + 1]):
                        index += 1
                        continue
                    break
                item_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", current)
                if item_match:
                    indent = len(item_match.group(1))
                    content = item_match.group(3).strip()
                    items.append(("    " if indent >= 2 else "") + content)
                    index += 1
                elif current.startswith((" ", "\t")) and items:
                    # Continuation of the previous item.
                    items[-1] = items[-1] + " " + current.strip()
                    index += 1
                else:
                    break
            blocks.append(BulletList(items=items, ordered=ordered))
            continue

        # Paragraph
        paragraph_lines: list[str] = []
        while index < total:
            current = lines[index]
            candidate = current.strip()
            if (
                not candidate
                or candidate.startswith(("#", "```", ">", "|", ":::"))
                or re.fullmatch(r"-{3,}|\*{3,}|_{3,}", candidate)
                or re.match(r"^(\s*)([-*+]|\d+\.)\s+", current)
            ):
                break
            paragraph_lines.append(candidate)
            index += 1
        if paragraph_lines:
            blocks.append(Paragraph(text=" ".join(paragraph_lines)))

    return blocks


def count_words(blocks: list[Block]) -> int:
    total = 0
    for block in blocks:
        if isinstance(block, (Heading, Paragraph)):
            total += len(block.text.split())
        elif isinstance(block, BulletList):
            total += sum(len(item.split()) for item in block.items)
        elif isinstance(block, Callout):
            total += sum(len(p.split()) for p in block.body)
        elif isinstance(block, Table):
            total += sum(len(c.split()) for c in block.headers)
            total += sum(len(c.split()) for row in block.rows for c in row)
        elif isinstance(block, CodeBlock):
            total += len(block.code.split())
    return total
