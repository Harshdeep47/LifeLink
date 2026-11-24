"""Vector diagram renderer for the books.

Diagrams are written in a small declarative DSL inside ```diagram fences and
rendered as real ReportLab vector graphics. They are not ASCII art: a book that
claims to illustrate an architecture should contain drawings that scale, print
and extract cleanly.

The DSL deliberately has no free-form positioning. Nodes are placed on a grid of
rows and columns, which keeps every diagram aligned and makes it impossible to
produce the overlapping boxes that hand-positioned diagrams drift into.

    type: layered | flow | sequence | table-shape
    title: optional caption shown above the drawing

    layered:
        layer <Label>
        node <id> <Label> [style=aws|domain|data|external|user]
        edge <from> -> <to> [label]

    sequence:
        actor <id> <Label>
        msg <from> -> <to> <Label>
        note <Label>
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm

# Palette shared with the application's design tokens.
CRIMSON = colors.HexColor("#981425")
CRIMSON_LIGHT = colors.HexColor("#fbe8ea")
NAVY = colors.HexColor("#1b2439")
NAVY_LIGHT = colors.HexColor("#e8ecf3")
GREY_LINE = colors.HexColor("#a8b0c0")
GREY_FILL = colors.HexColor("#f1f4f8")
GREEN = colors.HexColor("#0f7a4f")
GREEN_LIGHT = colors.HexColor("#e6f5ee")
AMBER = colors.HexColor("#9a6300")
AMBER_LIGHT = colors.HexColor("#fdf3e0")
WHITE = colors.white

STYLES = {
    "aws": (CRIMSON, CRIMSON_LIGHT),
    "domain": (NAVY, NAVY_LIGHT),
    "data": (GREEN, GREEN_LIGHT),
    "external": (AMBER, AMBER_LIGHT),
    "user": (NAVY, WHITE),
    "default": (NAVY, GREY_FILL),
}


@dataclass
class Node:
    identifier: str
    label: str
    style: str = "default"
    layer: int = 0
    column: int = 0
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""


@dataclass
class DiagramSpec:
    kind: str = "layered"
    title: str = ""
    layers: list[str] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    actors: list[Node] = field(default_factory=list)
    messages: list[Edge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_diagram(spec_text: str) -> DiagramSpec:
    spec = DiagramSpec()
    current_layer = -1

    for raw in spec_text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("type:"):
            spec.kind = line.split(":", 1)[1].strip()
            continue
        if line.startswith("title:"):
            spec.title = line.split(":", 1)[1].strip()
            continue

        if line.startswith("layer "):
            spec.layers.append(line[6:].strip())
            current_layer = len(spec.layers) - 1
            continue

        if line.startswith("node "):
            rest = line[5:].strip()
            style = "default"
            style_match = re.search(r"\bstyle=(\w+)\s*$", rest)
            if style_match:
                style = style_match.group(1)
                rest = rest[: style_match.start()].strip()
            parts = rest.split(None, 1)
            identifier = parts[0]
            label = parts[1] if len(parts) > 1 else identifier
            column = sum(1 for n in spec.nodes if n.layer == max(current_layer, 0))
            spec.nodes.append(
                Node(
                    identifier=identifier,
                    label=label,
                    style=style,
                    layer=max(current_layer, 0),
                    column=column,
                )
            )
            continue

        if line.startswith("actor "):
            parts = line[6:].strip().split(None, 1)
            spec.actors.append(
                Node(identifier=parts[0], label=parts[1] if len(parts) > 1 else parts[0])
            )
            continue

        if line.startswith("edge ") or line.startswith("msg "):
            body = line.split(None, 1)[1]
            match = re.match(r"^(\S+)\s*->\s*(\S+)\s*(.*)$", body)
            if match:
                edge = Edge(
                    source=match.group(1),
                    target=match.group(2),
                    label=match.group(3).strip(),
                )
                if line.startswith("edge "):
                    spec.edges.append(edge)
                else:
                    spec.messages.append(edge)
            continue

        if line.startswith("note "):
            spec.notes.append(line[5:].strip())
            continue

    return spec


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _draw_box(drawing: Drawing, node: Node, font_size: float = 7.2) -> None:
    stroke, fill = STYLES.get(node.style, STYLES["default"])
    drawing.add(
        Rect(
            node.x, node.y, node.width, node.height,
            fillColor=fill, strokeColor=stroke, strokeWidth=0.9, rx=3, ry=3,
        )
    )
    max_chars = max(8, int(node.width / (font_size * 0.52)))
    lines = _wrap(node.label, max_chars)
    # Vertically centre the text block inside the box.
    total_height = len(lines) * (font_size + 1.6)
    start_y = node.y + (node.height - total_height) / 2 + total_height - font_size
    for offset, text in enumerate(lines):
        drawing.add(
            String(
                node.x + node.width / 2,
                start_y - offset * (font_size + 1.6),
                text,
                fontName="Helvetica-Bold" if offset == 0 else "Helvetica",
                fontSize=font_size,
                fillColor=stroke if node.style != "user" else NAVY,
                textAnchor="middle",
            )
        )


def _arrow(drawing: Drawing, x1: float, y1: float, x2: float, y2: float,
           label: str = "", colour=GREY_LINE) -> None:
    drawing.add(Line(x1, y1, x2, y2, strokeColor=colour, strokeWidth=0.9))
    # Arrowhead
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 3.4
    for sign in (1, -1):
        drawing.add(
            Line(
                x2, y2,
                x2 - size * math.cos(angle - sign * 0.45),
                y2 - size * math.sin(angle - sign * 0.45),
                strokeColor=colour, strokeWidth=0.9,
            )
        )
    if label:
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        drawing.add(
            String(
                mid_x + 3, mid_y + 2, label,
                fontName="Helvetica", fontSize=6.2, fillColor=NAVY,
            )
        )


def render_layered(spec: DiagramSpec, width: float) -> Drawing:
    """Layered architecture diagram: labelled bands of boxes, top to bottom."""
    layer_count = max(1, len(spec.layers) or (max((n.layer for n in spec.nodes), default=0) + 1))
    by_layer: dict[int, list[Node]] = {}
    for node in spec.nodes:
        by_layer.setdefault(node.layer, []).append(node)

    box_height = 15 * mm
    layer_gap = 9 * mm
    label_width = 26 * mm
    top_padding = 6 * mm if spec.title else 2 * mm

    height = top_padding + layer_count * box_height + (layer_count - 1) * layer_gap + 4 * mm
    drawing = Drawing(width, height)

    if spec.title:
        drawing.add(
            String(
                0, height - 4 * mm, spec.title,
                fontName="Helvetica-Bold", fontSize=8.4, fillColor=NAVY,
            )
        )

    usable = width - label_width - 2 * mm

    for layer_index in range(layer_count):
        nodes = by_layer.get(layer_index, [])
        y = height - top_padding - (layer_index + 1) * box_height - layer_index * layer_gap

        if layer_index < len(spec.layers):
            drawing.add(
                String(
                    0, y + box_height / 2 - 2.4, spec.layers[layer_index],
                    fontName="Helvetica-Bold", fontSize=6.6, fillColor=colors.HexColor("#5a6478"),
                )
            )
            drawing.add(
                Line(
                    0, y + box_height + layer_gap / 2 - 1,
                    width, y + box_height + layer_gap / 2 - 1,
                    strokeColor=colors.HexColor("#e4e8ef"), strokeWidth=0.6,
                )
            )

        if not nodes:
            continue

        gap = 4 * mm
        node_width = (usable - gap * (len(nodes) - 1)) / len(nodes)
        for position, node in enumerate(nodes):
            node.x = label_width + 2 * mm + position * (node_width + gap)
            node.y = y
            node.width = node_width
            node.height = box_height
            _draw_box(drawing, node)

    positions = {n.identifier: n for n in spec.nodes}
    for edge in spec.edges:
        source = positions.get(edge.source)
        target = positions.get(edge.target)
        if not source or not target:
            continue
        if source.layer == target.layer:
            # Sideways within a band.
            if source.x < target.x:
                _arrow(drawing, source.x + source.width, source.y + source.height / 2,
                       target.x, target.y + target.height / 2, edge.label)
            else:
                _arrow(drawing, source.x, source.y + source.height / 2,
                       target.x + target.width, target.y + target.height / 2, edge.label)
        else:
            start_y = source.y if source.layer < target.layer else source.y + source.height
            end_y = target.y + target.height if source.layer < target.layer else target.y
            _arrow(drawing, source.x + source.width / 2, start_y,
                   target.x + target.width / 2, end_y, edge.label)

    return drawing


def render_sequence(spec: DiagramSpec, width: float) -> Drawing:
    """Sequence diagram: lifelines with ordered messages."""
    actors = spec.actors or [Node(identifier=f"a{i}", label=f"Actor {i}") for i in range(2)]
    message_count = max(1, len(spec.messages))

    header_height = 11 * mm
    row_height = 7.4 * mm
    note_height = 5.6 * mm * len(spec.notes)
    top_padding = 6 * mm if spec.title else 0

    height = top_padding + header_height + message_count * row_height + note_height + 6 * mm
    drawing = Drawing(width, height)

    if spec.title:
        drawing.add(
            String(0, height - 4 * mm, spec.title,
                   fontName="Helvetica-Bold", fontSize=8.4, fillColor=NAVY)
        )

    column_width = width / len(actors)
    centres: dict[str, float] = {}

    for index, actor in enumerate(actors):
        centre = index * column_width + column_width / 2
        centres[actor.identifier] = centre
        box_width = min(column_width - 4 * mm, 34 * mm)
        actor.x = centre - box_width / 2
        actor.y = height - top_padding - header_height
        actor.width = box_width
        actor.height = 9 * mm
        actor.style = "domain"
        _draw_box(drawing, actor, font_size=6.8)
        # Lifeline
        drawing.add(
            Line(
                centre, 4 * mm, centre, actor.y,
                strokeColor=colors.HexColor("#cfd5e0"), strokeWidth=0.6,
            )
        )

    y = height - top_padding - header_height - 5 * mm
    for message in spec.messages:
        source = centres.get(message.source)
        target = centres.get(message.target)
        if source is None or target is None:
            y -= row_height
            continue
        if abs(source - target) < 1:
            # Self-message: a small loop to the right of the lifeline.
            drawing.add(
                PolyLine(
                    [source, y, source + 9 * mm, y, source + 9 * mm, y - 3.4 * mm,
                     source + 1.4 * mm, y - 3.4 * mm],
                    strokeColor=CRIMSON, strokeWidth=0.9,
                )
            )
            drawing.add(
                String(source + 11 * mm, y - 2.6 * mm, message.label,
                       fontName="Helvetica", fontSize=6.2, fillColor=NAVY)
            )
        else:
            _arrow(drawing, source, y, target, y, "", CRIMSON)
            drawing.add(
                String(
                    (source + target) / 2, y + 2.2, message.label,
                    fontName="Helvetica", fontSize=6.2, fillColor=NAVY, textAnchor="middle",
                )
            )
        y -= row_height

    for note in spec.notes:
        drawing.add(
            String(0, y, f"Note: {note}",
                   fontName="Helvetica-Oblique", fontSize=6.2,
                   fillColor=colors.HexColor("#5a6478"))
        )
        y -= 5.6 * mm

    return drawing


def render_flow(spec: DiagramSpec, width: float) -> Drawing:
    """Left-to-right flow, wrapping into rows of three."""
    nodes = spec.nodes
    if not nodes:
        return Drawing(width, 10 * mm)

    per_row = 3
    rows = (len(nodes) + per_row - 1) // per_row
    box_height = 14 * mm
    row_gap = 10 * mm
    top_padding = 6 * mm if spec.title else 0

    height = top_padding + rows * box_height + (rows - 1) * row_gap + 4 * mm
    drawing = Drawing(width, height)

    if spec.title:
        drawing.add(
            String(0, height - 4 * mm, spec.title,
                   fontName="Helvetica-Bold", fontSize=8.4, fillColor=NAVY)
        )

    gap = 8 * mm
    for index, node in enumerate(nodes):
        row = index // per_row
        column = index % per_row
        in_row = min(per_row, len(nodes) - row * per_row)
        node_width = (width - gap * (in_row - 1)) / in_row
        node.x = column * (node_width + gap)
        node.y = height - top_padding - (row + 1) * box_height - row * row_gap
        node.width = node_width
        node.height = box_height
        _draw_box(drawing, node)

    for index in range(len(nodes) - 1):
        current = nodes[index]
        following = nodes[index + 1]
        if index % per_row == per_row - 1:
            # Wrap to the next row: drop down from the last box.
            _arrow(drawing, current.x + current.width / 2, current.y,
                   following.x + following.width / 2, following.y + following.height)
        else:
            _arrow(drawing, current.x + current.width, current.y + current.height / 2,
                   following.x, following.y + following.height / 2)

    return drawing


def render(spec_text: str, width: float) -> Drawing:
    spec = parse_diagram(spec_text)
    if spec.kind == "sequence":
        return render_sequence(spec, width)
    if spec.kind == "flow":
        return render_flow(spec, width)
    return render_layered(spec, width)
