"""Markdown to PDF book builder.

Produces a professionally laid-out technical book: cover, title verso, table of
contents with real page numbers, running headers and footers, numbered figures
and tables, syntax-tinted code blocks, and a colophon.

Two layout problems get explicit attention because they are what makes
hand-rolled PDFs look amateur:

* **Code blocks that run off the page.** Code is wrapped at a measured character
  width rather than hoped to fit, and a continuation marker shows where a line
  was broken, so no code is silently clipped.
* **Table columns that collide.** Column widths are computed from content with a
  minimum, then scaled to the frame, and cells wrap as paragraphs rather than
  overflowing.

The table of contents needs page numbers that are only known after layout, so
the document is built twice: the first pass records where each heading landed,
the second pass renders the contents page using those numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from . import diagrams
from .markdown_blocks import (
    BulletList,
    Callout,
    CodeBlock,
    Diagram,
    Heading,
    PageBreak as MdPageBreak,
    Paragraph as MdParagraph,
    Rule,
    Table as MdTable,
    parse_markdown,
)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 22 * mm
MARGIN_RIGHT = 18 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 20 * mm
FRAME_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

CRIMSON = colors.HexColor("#981425")
CRIMSON_DEEP = colors.HexColor("#5c0a14")
NAVY = colors.HexColor("#0f172a")
NAVY_SOFT = colors.HexColor("#2b3650")
GREY = colors.HexColor("#5a6478")
GREY_LIGHT = colors.HexColor("#e4e8ef")
GREY_BG = colors.HexColor("#f6f8fb")
CODE_BG = colors.HexColor("#f4f6fa")
CODE_BORDER = colors.HexColor("#d9dfe9")

CALLOUT_COLOURS = {
    "note": (colors.HexColor("#2b5f8a"), colors.HexColor("#eef4fa")),
    "warning": (colors.HexColor("#9a6300"), colors.HexColor("#fdf6e8")),
    "key": (CRIMSON, colors.HexColor("#fdf0f1")),
    "quote": (GREY, GREY_BG),
}

PYTHON_KEYWORDS = {
    "def", "class", "return", "if", "elif", "else", "for", "while", "try", "except",
    "finally", "raise", "import", "from", "as", "with", "yield", "lambda", "not",
    "and", "or", "in", "is", "None", "True", "False", "async", "await", "pass",
    "break", "continue", "assert", "global", "nonlocal", "del", "self", "match", "case",
}


@dataclass
class BookMeta:
    title: str
    subtitle: str
    volume: str
    version: str
    generated: str
    description: str
    source_note: str


class HeadingAnchor(Flowable):
    """Zero-height marker that records the page a heading landed on.

    Used by the first pass so the contents page can be rendered with real page
    numbers on the second.
    """

    def __init__(self, level: int, text: str, registry: list):
        super().__init__()
        self.level = level
        self.text = text
        self.registry = registry
        self.width = 0
        self.height = 0

    def wrap(self, available_width, available_height):
        return (0, 0)

    def draw(self):
        page = self.canv.getPageNumber()
        self.registry.append((self.level, self.text, page))


class HorizontalRule(Flowable):
    def __init__(self, width: float, thickness: float = 0.6, colour=GREY_LIGHT):
        super().__init__()
        self.width = width
        self.thickness = thickness
        self.colour = colour
        self.height = 5 * mm

    def wrap(self, available_width, available_height):
        return (available_width, self.height)

    def draw(self):
        self.canv.setStrokeColor(self.colour)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.height / 2, self.width, self.height / 2)


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    # allowWidows=0 stops a paragraph leaving its final line alone on the next
    # page, which otherwise produces a page containing a single orphaned word.
    styles["body"] = ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.6,
        leading=14.4, alignment=TA_JUSTIFY, textColor=NAVY_SOFT,
        spaceBefore=0, spaceAfter=5.5, allowWidows=0, allowOrphans=0,
    )
    styles["h1"] = ParagraphStyle(
        "h1", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=CRIMSON_DEEP,
        spaceBefore=0, spaceAfter=8, alignment=TA_LEFT,
    )
    styles["h2"] = ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=14.5, leading=18, textColor=NAVY,
        spaceBefore=12, spaceAfter=6,
    )
    styles["h3"] = ParagraphStyle(
        "h3", fontName="Helvetica-Bold", fontSize=11.6, leading=15, textColor=NAVY,
        spaceBefore=10, spaceAfter=4,
    )
    styles["h4"] = ParagraphStyle(
        "h4", fontName="Helvetica-Bold", fontSize=10.2, leading=13.4, textColor=NAVY_SOFT,
        spaceBefore=8, spaceAfter=3,
    )
    styles["h5"] = ParagraphStyle(
        "h5", fontName="Helvetica-BoldOblique", fontSize=9.6, leading=13,
        textColor=GREY, spaceBefore=7, spaceAfter=3,
    )
    styles["h6"] = styles["h5"]
    styles["bullet"] = ParagraphStyle(
        "bullet", parent=styles["body"], leftIndent=11, bulletIndent=2,
        spaceAfter=2.6, alignment=TA_LEFT, allowWidows=0, allowOrphans=0,
    )
    styles["bullet_nested"] = ParagraphStyle(
        "bullet_nested", parent=styles["bullet"], leftIndent=24, bulletIndent=15,
        fontSize=9.2, leading=13,
    )
    styles["code"] = ParagraphStyle(
        "code", fontName="Courier", fontSize=7.9, leading=10.4, textColor=NAVY,
        alignment=TA_LEFT, spaceBefore=0, spaceAfter=0,
    )
    styles["caption"] = ParagraphStyle(
        "caption", fontName="Helvetica-Oblique", fontSize=8, leading=11,
        textColor=GREY, alignment=TA_LEFT, spaceBefore=3, spaceAfter=8,
    )
    styles["table_header"] = ParagraphStyle(
        "table_header", fontName="Helvetica-Bold", fontSize=8.1, leading=10.6,
        textColor=NAVY, alignment=TA_LEFT,
    )
    styles["table_cell"] = ParagraphStyle(
        "table_cell", fontName="Helvetica", fontSize=8.1, leading=10.6,
        textColor=NAVY_SOFT, alignment=TA_LEFT,
    )
    styles["callout_title"] = ParagraphStyle(
        "callout_title", fontName="Helvetica-Bold", fontSize=9.4, leading=12.6,
        textColor=NAVY, spaceAfter=2.6,
    )
    styles["callout_body"] = ParagraphStyle(
        "callout_body", fontName="Helvetica", fontSize=9.2, leading=13,
        textColor=NAVY_SOFT, alignment=TA_LEFT, spaceAfter=3,
        allowWidows=0, allowOrphans=0,
    )
    styles["toc_chapter"] = ParagraphStyle(
        "toc_chapter", fontName="Helvetica-Bold", fontSize=9.8, leading=15,
        textColor=NAVY, spaceBefore=4,
    )
    styles["toc_section"] = ParagraphStyle(
        "toc_section", fontName="Helvetica", fontSize=9, leading=13.4,
        textColor=NAVY_SOFT, leftIndent=12,
    )
    styles["cover_title"] = ParagraphStyle(
        "cover_title", fontName="Helvetica-Bold", fontSize=34, leading=38,
        textColor=colors.white, alignment=TA_LEFT,
    )
    styles["cover_subtitle"] = ParagraphStyle(
        "cover_subtitle", fontName="Helvetica", fontSize=14, leading=19,
        textColor=colors.HexColor("#f6dfe2"), alignment=TA_LEFT,
    )
    return styles


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_markup(text: str) -> str:
    """Convert inline Markdown to ReportLab markup, escaping first.

    Code spans are protected before escaping so backtick content is never
    interpreted as markup.
    """
    placeholders: dict[str, str] = {}

    def protect(match):
        token = f"\x00{len(placeholders)}\x00"
        placeholders[token] = match.group(1)
        return token

    text = re.sub(r"`([^`]+)`", protect, text)
    text = escape(text)

    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    # Links: show the text, with the URL appended when it is external.
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: f"<font color='#981425'>{m.group(1)}</font>",
        text,
    )
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)

    for token, code in placeholders.items():
        text = text.replace(
            token,
            f"<font face='Courier' size='8.6' color='#7a0f1d'>{escape(code)}</font>",
        )
    return text


def wrap_code_line(line: str, max_chars: int) -> list[str]:
    """Wrap one code line at a measured width, marking continuations.

    Clipping is unacceptable in a technical book -- a reader cannot tell a
    deliberately short line from a truncated one -- so every break is visible.
    """
    if len(line) <= max_chars:
        return [line]

    indent_match = re.match(r"^(\s*)", line)
    indent = indent_match.group(1) if indent_match else ""
    continuation_indent = indent + "    "

    pieces: list[str] = []
    remaining = line
    first = True
    while remaining:
        limit = max_chars if first else max_chars - len(continuation_indent)
        limit = max(20, limit)
        if len(remaining) <= limit:
            pieces.append(remaining if first else continuation_indent + remaining.lstrip())
            break
        # Prefer breaking after a separator so the wrap reads naturally.
        window = remaining[:limit]
        cut = max(
            window.rfind(", "), window.rfind("("), window.rfind(" "),
            window.rfind("."), window.rfind("="),
        )
        if cut < limit * 0.5:
            cut = limit
        else:
            cut += 1
        head = remaining[:cut].rstrip()
        pieces.append(head if first else continuation_indent + head.lstrip())
        remaining = remaining[cut:].lstrip()
        first = False
    return pieces


COMMENT_INK = "#7b849a"
KEYWORD_INK = "#7a0f1d"
STRING_INK = "#0f7a4f"

# One pass over the raw line. Ordering matters: comments and strings are matched
# before keywords so a keyword inside a string is not tinted as code.
TOKENISERS: dict[str, re.Pattern] = {
    "python": re.compile(
        r"(?P<comment>#.*$)"
        r"|(?P<string>\"\"\".*?\"\"\"|'''.*?'''|\"[^\"\n]*\"|'[^'\n]*')"
        r"|(?P<keyword>\b(?:" + "|".join(sorted(PYTHON_KEYWORDS, key=len, reverse=True)) + r")\b)"
    ),
    "yaml": re.compile(
        r"(?P<comment>#.*$)"
        r"|(?P<string>\"[^\"\n]*\"|'[^'\n]*')"
        r"|(?P<key>^\s*[A-Za-z0-9_.\-]+(?=:))"
    ),
    "json": re.compile(
        r"(?P<key>\"[^\"\n]*\"(?=\s*:))"
        r"|(?P<string>\"[^\"\n]*\")"
    ),
    "shell": re.compile(r"(?P<comment>#.*$)"),
}
TOKENISERS["py"] = TOKENISERS["python"]
TOKENISERS["yml"] = TOKENISERS["yaml"]
for _alias in ("bash", "sh", "console"):
    TOKENISERS[_alias] = TOKENISERS["shell"]

TOKEN_INK = {
    "comment": (COMMENT_INK, "i"),
    "string": (STRING_INK, None),
    "keyword": (KEYWORD_INK, "b"),
    "key": (KEYWORD_INK, None),
}


def _code_text(fragment: str) -> str:
    """Escape a code fragment and preserve its spacing.

    Spaces become non-breaking so indentation and alignment survive, but this is
    applied ONLY to text fragments -- never to generated markup, where it would
    corrupt tag attributes.
    """
    return escape(fragment).replace(" ", "&nbsp;")


def highlight_code(line: str, language: str) -> str:
    """Light syntax tinting: comments, strings and keywords.

    Implemented as a single tokenising pass rather than successive regex
    substitutions. Chained substitutions re-match the markup inserted by earlier
    passes -- a colour code like '#7a0f1d' looks exactly like a string literal --
    which produced malformed tags and a parse failure.
    """
    pattern = TOKENISERS.get(language)
    if pattern is None:
        return _code_text(line)

    out: list[str] = []
    position = 0
    for match in pattern.finditer(line):
        if match.start() > position:
            out.append(_code_text(line[position:match.start()]))
        kind = match.lastgroup or ""
        text = _code_text(match.group())
        ink, emphasis = TOKEN_INK.get(kind, (None, None))
        if ink:
            inner = f"<{emphasis}>{text}</{emphasis}>" if emphasis else text
            out.append(f"<font color='{ink}'>{inner}</font>")
        else:
            out.append(text)
        position = match.end()
    if position < len(line):
        out.append(_code_text(line[position:]))
    return "".join(out)


class BookBuilder:
    def __init__(self, meta: BookMeta, styles: dict[str, ParagraphStyle] | None = None):
        self.meta = meta
        self.styles = styles or build_styles()
        self.figure_number = 0
        self.table_number = 0
        self.headings: list[tuple[int, str, int]] = []

    # --- page furniture ---

    def _draw_cover(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(CRIMSON_DEEP)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

        # Diagonal banding, echoing the application's demo banner.
        canvas.setFillColor(colors.HexColor("#7a0f1d"))
        for offset in range(-14, 30):
            x = offset * 26
            canvas.saveState()
            canvas.translate(x, 0)
            canvas.rotate(18)
            canvas.rect(0, -120, 13, PAGE_HEIGHT + 260, fill=1, stroke=0)
            canvas.restoreState()

        canvas.setFillColor(colors.HexColor("#5c0a14"))
        canvas.rect(0, PAGE_HEIGHT - 300 * mm, PAGE_WIDTH, 120 * mm, fill=1, stroke=0)

        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(MARGIN_LEFT, PAGE_HEIGHT - 30 * mm, "LIFELINK")
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#f0c9ce"))
        canvas.drawString(
            MARGIN_LEFT, PAGE_HEIGHT - 36 * mm,
            "Blood availability, discovery, donation and emergency coordination",
        )

        canvas.setStrokeColor(colors.HexColor("#c62436"))
        canvas.setLineWidth(2.4)
        canvas.line(MARGIN_LEFT, PAGE_HEIGHT - 42 * mm, PAGE_WIDTH - MARGIN_RIGHT,
                    PAGE_HEIGHT - 42 * mm)

        canvas.setFillColor(colors.HexColor("#f6dfe2"))
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(MARGIN_LEFT, PAGE_HEIGHT - 60 * mm, self.meta.volume.upper())

        # Title, wrapped by hand so the cover never clips.
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 30)
        y = PAGE_HEIGHT - 76 * mm
        for line in self._wrap_for_canvas(self.meta.title, "Helvetica-Bold", 30,
                                          FRAME_WIDTH):
            canvas.drawString(MARGIN_LEFT, y, line)
            y -= 13 * mm

        canvas.setFillColor(colors.HexColor("#f0c9ce"))
        canvas.setFont("Helvetica", 13)
        y -= 4 * mm
        for line in self._wrap_for_canvas(self.meta.subtitle, "Helvetica", 13, FRAME_WIDTH):
            canvas.drawString(MARGIN_LEFT, y, line)
            y -= 7 * mm

        canvas.setFillColor(colors.HexColor("#e9b8bf"))
        canvas.setFont("Helvetica", 9.4)
        y -= 6 * mm
        for line in self._wrap_for_canvas(self.meta.description, "Helvetica", 9.4,
                                          FRAME_WIDTH * 0.86):
            canvas.drawString(MARGIN_LEFT, y, line)
            y -= 5.2 * mm

        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(MARGIN_LEFT, 34 * mm, f"Version {self.meta.version}")
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#f0c9ce"))
        canvas.drawString(MARGIN_LEFT, 28 * mm, f"Generated {self.meta.generated}")
        canvas.setFont("Helvetica-Oblique", 8)
        canvas.drawString(MARGIN_LEFT, 20 * mm, self.meta.source_note)
        canvas.restoreState()

    @staticmethod
    def _wrap_for_canvas(text: str, font: str, size: float, width: float) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if stringWidth(candidate, font, size) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def _draw_content_page(self, canvas, doc):
        canvas.saveState()
        page = canvas.getPageNumber()

        # Running header
        canvas.setStrokeColor(GREY_LIGHT)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN_LEFT, PAGE_HEIGHT - MARGIN_TOP + 7 * mm,
                    PAGE_WIDTH - MARGIN_RIGHT, PAGE_HEIGHT - MARGIN_TOP + 7 * mm)
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(GREY)
        canvas.drawString(MARGIN_LEFT, PAGE_HEIGHT - MARGIN_TOP + 9.6 * mm,
                          f"LifeLink — {self.meta.volume}")
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, PAGE_HEIGHT - MARGIN_TOP + 9.6 * mm,
                               self.meta.title)

        # Footer
        canvas.line(MARGIN_LEFT, MARGIN_BOTTOM - 6 * mm,
                    PAGE_WIDTH - MARGIN_RIGHT, MARGIN_BOTTOM - 6 * mm)
        canvas.setFont("Helvetica", 7.6)
        canvas.drawString(MARGIN_LEFT, MARGIN_BOTTOM - 10.4 * mm,
                          "Synthetic demonstration data. Not for clinical use.")
        canvas.setFont("Helvetica-Bold", 8.4)
        canvas.setFillColor(NAVY_SOFT)
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, MARGIN_BOTTOM - 10.4 * mm, str(page))
        canvas.restoreState()

    # --- block rendering ---

    def _code_flowable(self, block: CodeBlock) -> list[Flowable]:
        inner_width = FRAME_WIDTH - 10 * mm
        max_chars = max(40, int(inner_width / stringWidth("0", "Courier", 7.9)))

        rendered: list[str] = []
        for raw_line in block.code.split("\n"):
            for piece in wrap_code_line(raw_line.rstrip(), max_chars):
                rendered.append(highlight_code(piece, block.language))

        if not rendered:
            rendered = [""]

        # highlight_code has already escaped the text and converted spaces to
        # non-breaking ones, so nothing further may be substituted here.
        paragraphs = [
            [Paragraph(line or "&nbsp;", self.styles["code"])] for line in rendered
        ]
        table = Table(paragraphs, colWidths=[inner_width])
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, CODE_BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 0.6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )

        parts: list[Flowable] = [Spacer(1, 3), table]
        if block.caption:
            parts.append(Paragraph(inline_markup(block.caption), self.styles["caption"]))
        else:
            parts.append(Spacer(1, 7))

        # Short blocks stay with their caption; long ones are returned as a
        # plain list so they may split across pages rather than leaving a gap.
        # They must NOT be wrapped in a zero-height custom flowable: ReportLab
        # never splits one, so its contents are silently dropped.
        if len(rendered) <= 26:
            return [KeepTogether(parts)]
        return parts

    def _table_flowable(self, block: MdTable) -> list[Flowable]:
        self.table_number += 1
        column_count = len(block.headers)

        # Width from content, with a floor, then scaled to the frame.
        weights: list[float] = []
        for index in range(column_count):
            cells = [block.headers[index]] + [
                row[index] for row in block.rows if index < len(row)
            ]
            longest = max((len(re.sub(r"[*`_]", "", c)) for c in cells), default=6)
            weights.append(max(7.0, min(float(longest), 54.0)))
        total = sum(weights) or 1.0
        widths = [FRAME_WIDTH * (w / total) for w in weights]

        data = [[Paragraph(inline_markup(h), self.styles["table_header"]) for h in block.headers]]
        for row in block.rows:
            data.append([
                Paragraph(inline_markup(cell), self.styles["table_cell"]) for cell in row
            ])

        table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), GREY_BG),
            ("LINEBELOW", (0, 0), (-1, 0), 0.9, colors.HexColor("#c2cad8")),
            ("LINEBELOW", (0, 1), (-1, -2), 0.35, GREY_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.6, GREY_LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
            ("TOPPADDING", (0, 0), (-1, -1), 3.4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
        ]
        for index, alignment in enumerate(block.alignments[:column_count]):
            if alignment in ("RIGHT", "CENTER"):
                style.append(("ALIGN", (index, 0), (index, -1), alignment))
        table.setStyle(TableStyle(style))

        caption_text = block.caption or f"Table {self.table_number}"
        parts: list[Flowable] = [
            Spacer(1, 3),
            table,
            Paragraph(
                inline_markup(
                    caption_text if caption_text.lower().startswith("table")
                    else f"Table {self.table_number}. {caption_text}"
                ),
                self.styles["caption"],
            ),
        ]
        if len(block.rows) <= 12:
            return [KeepTogether(parts)]
        return parts

    def _callout_flowable(self, block: Callout) -> Flowable:
        accent, background = CALLOUT_COLOURS.get(block.kind, CALLOUT_COLOURS["note"])
        inner: list[Flowable] = []
        if block.title:
            inner.append(Paragraph(inline_markup(block.title), self.styles["callout_title"]))
        for paragraph in block.body:
            inner.append(Paragraph(inline_markup(paragraph), self.styles["callout_body"]))
        if not inner:
            inner.append(Paragraph("&nbsp;", self.styles["callout_body"]))

        table = Table([[inner]], colWidths=[FRAME_WIDTH])
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("LINEBEFORE", (0, 0), (0, -1), 2.6, accent),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde3ec")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        return KeepTogether([Spacer(1, 4), table, Spacer(1, 7)])

    def _diagram_flowable(self, block: Diagram) -> Flowable:
        self.figure_number += 1
        drawing = diagrams.render(block.spec, FRAME_WIDTH)
        caption_text = block.caption or "Architecture diagram"
        caption = (
            caption_text
            if caption_text.lower().startswith("figure")
            else f"Figure {self.figure_number}. {caption_text}"
        )
        return KeepTogether([
            Spacer(1, 5),
            drawing,
            Paragraph(inline_markup(caption), self.styles["caption"]),
        ])

    def blocks_to_flowables(self, blocks, *, record_headings: bool) -> list[Flowable]:
        flowables: list[Flowable] = []
        self.figure_number = 0
        self.table_number = 0

        def append_page_break() -> None:
            """Add a page break unless one is already pending.

            A chapter heading forces a new page, and the source also carries an
            explicit page-break marker before each chapter. Two consecutive
            breaks produce a genuinely blank page, which the specification
            lists among the things to avoid.
            """
            if flowables and isinstance(flowables[-1], PageBreak):
                return
            flowables.append(PageBreak())

        for block in blocks:
            if isinstance(block, Heading):
                if block.level == 1:
                    append_page_break()
                    if record_headings:
                        flowables.append(HeadingAnchor(1, block.text, self.headings))
                    flowables.append(Paragraph(inline_markup(block.text), self.styles["h1"]))
                    flowables.append(HorizontalRule(FRAME_WIDTH, 1.4, CRIMSON))
                else:
                    style = self.styles.get(f"h{block.level}", self.styles["h4"])
                    # Avoid a heading stranded at the foot of a page.
                    flowables.append(CondPageBreak(26 * mm))
                    if record_headings and block.level == 2:
                        flowables.append(HeadingAnchor(2, block.text, self.headings))
                    flowables.append(Paragraph(inline_markup(block.text), style))
            elif isinstance(block, MdParagraph):
                flowables.append(Paragraph(inline_markup(block.text), self.styles["body"]))
            elif isinstance(block, BulletList):
                for position, item in enumerate(block.items, start=1):
                    nested = item.startswith("    ")
                    style = self.styles["bullet_nested"] if nested else self.styles["bullet"]
                    text = item.strip()
                    bullet = f"{position}." if block.ordered and not nested else "•"
                    flowables.append(
                        Paragraph(inline_markup(text), style, bulletText=bullet)
                    )
                flowables.append(Spacer(1, 4))
            elif isinstance(block, CodeBlock):
                flowables.extend(self._code_flowable(block))
            elif isinstance(block, MdTable):
                flowables.extend(self._table_flowable(block))
            elif isinstance(block, Callout):
                flowables.append(self._callout_flowable(block))
            elif isinstance(block, Diagram):
                flowables.append(self._diagram_flowable(block))
            elif isinstance(block, Rule):
                flowables.append(HorizontalRule(FRAME_WIDTH))
            elif isinstance(block, MdPageBreak):
                append_page_break()

        return flowables

    # --- front matter ---

    def _front_matter(self) -> list[Flowable]:
        parts: list[Flowable] = [
            # The cover is page one and is drawn entirely by _draw_cover, so it
            # needs a token flowable to exist plus an explicit switch to the
            # content template for everything after it.
            Spacer(1, 1),
            NextPageTemplate("content"),
            PageBreak(),
            Paragraph(self.meta.title, self.styles["h1"]),
            HorizontalRule(FRAME_WIDTH, 1.4, CRIMSON),
            Paragraph(inline_markup(self.meta.subtitle), self.styles["body"]),
            Spacer(1, 6),
        ]
        detail_rows = [
            ["Volume", self.meta.volume],
            ["Version", self.meta.version],
            ["Generated", self.meta.generated],
            ["Source", self.meta.source_note],
        ]
        table = Table(
            [[Paragraph(f"<b>{k}</b>", self.styles["table_cell"]),
              Paragraph(inline_markup(v), self.styles["table_cell"])] for k, v in detail_rows],
            colWidths=[FRAME_WIDTH * 0.2, FRAME_WIDTH * 0.8],
            hAlign="LEFT",
        )
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.35, GREY_LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        parts.append(table)
        parts.append(Spacer(1, 10))
        parts.append(
            self._callout_flowable(
                Callout(
                    kind="warning",
                    title="Read this before relying on anything in this book",
                    body=[
                        "LifeLink is a demonstration system. All organizations, "
                        "facilities, stock records, camps, donors and emergency "
                        "requests described here are synthetic. No real institution "
                        "is represented and none is a partner.",
                        "The system is not a medical device, provides no clinical "
                        "advice, does not reserve blood and does not determine "
                        "clinical urgency or suitability. The blood compatibility "
                        "reference data it ships with has NOT been reviewed by a "
                        "qualified professional for this deployment.",
                        "Where this book describes something as not implemented, not "
                        "deployed or not tested, that statement is accurate and "
                        "deliberate.",
                    ],
                )
            )
        )
        return parts

    def _toc_flowables(self, headings: list[tuple[int, str, int]]) -> list[Flowable]:
        parts: list[Flowable] = [
            PageBreak(),
            Paragraph("Contents", self.styles["h1"]),
            HorizontalRule(FRAME_WIDTH, 1.4, CRIMSON),
            Spacer(1, 4),
        ]
        if not headings:
            parts.append(Paragraph("No chapters recorded.", self.styles["body"]))
            return parts

        rows = []
        for level, text, page in headings:
            style = self.styles["toc_chapter"] if level == 1 else self.styles["toc_section"]
            rows.append([
                Paragraph(inline_markup(text), style),
                Paragraph(
                    f"<font color='#5a6478' size='8.4'>{page}</font>",
                    ParagraphStyle("toc_page", alignment=2, fontName="Helvetica", fontSize=8.4),
                ),
            ])

        table = Table(rows, colWidths=[FRAME_WIDTH - 16 * mm, 16 * mm], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ]))
        parts.append(table)
        return parts

    # --- build ---

    def build(self, markdown_text: str, output_path: Path) -> dict:
        blocks = parse_markdown(markdown_text)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # The contents page needs page numbers that only exist after layout, and
        # inserting it shifts every page it is counting. Estimating its height
        # puts the whole table out by a page or two.
        #
        # Instead, pass one lays out a contents page of exactly the right shape
        # with placeholder numbers. Its height is therefore identical in both
        # passes, so the pages recorded in pass one are the pages the finished
        # book has, and pass two only substitutes the real numbers in.
        placeholder = [
            (block.level, block.text, 0)
            for block in blocks
            if isinstance(block, Heading) and block.level in (1, 2)
        ]

        self.headings = []
        first_pass = self._make_document(output_path.with_suffix(".pass1.pdf"))
        story = (
            self._front_matter()
            + self._toc_flowables(placeholder)
            + self.blocks_to_flowables(blocks, record_headings=True)
        )
        first_pass.multiBuild(story)
        recorded = list(self.headings)

        # Pass two: the same layout, with real page numbers in the contents.
        self.headings = []
        document = self._make_document(output_path)
        story = (
            self._front_matter()
            + self._toc_flowables(recorded)
            + self.blocks_to_flowables(blocks, record_headings=True)
        )
        document.multiBuild(story)

        # If the second pass moved anything, the contents would be wrong. Record
        # that rather than shipping a book whose page numbers silently drifted.
        drift = [
            (text, before, after)
            for (_, text, before), (_, _, after) in zip(recorded, self.headings)
            if before != after
        ]
        adjusted = self.headings or recorded

        pass1 = output_path.with_suffix(".pass1.pdf")
        if pass1.exists():
            pass1.unlink()

        return {
            "path": str(output_path),
            "chapters": sum(1 for level, _, _ in adjusted if level == 1),
            "sections": sum(1 for level, _, _ in adjusted if level == 2),
            "headings": adjusted,
            "figures": self.figure_number,
            "tables": self.table_number,
            "toc_drift": drift,
        }

    def _make_document(self, path: Path) -> BaseDocTemplate:
        document = BaseDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=MARGIN_LEFT,
            rightMargin=MARGIN_RIGHT,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=f"LifeLink — {self.meta.title}",
            author="LifeLink project",
            subject=self.meta.subtitle,
            creator="LifeLink bookgen",
        )
        frame = Frame(
            MARGIN_LEFT, MARGIN_BOTTOM, FRAME_WIDTH,
            PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
            id="content", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )
        document.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self._draw_cover),
            PageTemplate(id="content", frames=[frame], onPage=self._draw_content_page),
        ])
        return document


