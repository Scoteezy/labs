"""Учебные SVG и проверка наблюдаемых признаков для инструкции 1.0."""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET

SIZE = 720
MIN_RADIUS = 16
MINIMAL = "минимализм"
DETAILED = "детализация"
REVIEW = "спорный"
SVG = "{http://www.w3.org/2000/svg}"

# Each family owns its layout and a fictional author/series pair from lab05.
LAYOUTS = (
    ((125, 320), (250, 320), (375, 320), (500, 320), (625, 320), (190, 445), (440, 445)),
    ((155, 460), (210, 330), (295, 220), (425, 185), (545, 240), (610, 365), (560, 505)),
    ((135, 160), (220, 235), (305, 310), (390, 385), (475, 460), (560, 535), (645, 610)),
    ((360, 125), (535, 195), (605, 365), (505, 535), (330, 595), (160, 475), (150, 275)),
    ((205, 210), (365, 210), (525, 210), (205, 385), (365, 385), (525, 385), (365, 555)),
    ((255, 135), (255, 272), (255, 409), (255, 546), (465, 204), (465, 341), (465, 478)),
)
COLORS = ("#224b79", "#6a4074", "#ad502b", "#32745e", "#24616b", "#8a611e")
BACKGROUNDS = ("#faf7f0", "#f4eff6", "#ffefe6", "#edf5ed", "#ecf2f6", "#fbf1db")


def svg_document(circles: list[tuple[int, int, int]], color: str, background: str) -> bytes:
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" '
        f'viewBox="0 0 {SIZE} {SIZE}">',
        f'<rect width="{SIZE}" height="{SIZE}" fill="{background}"/>',
        f'<rect x="55" y="55" width="610" height="610" rx="22" fill="none" '
        f'stroke="{color}" stroke-width="2"/>',
    ]
    for x, y, radius in circles:
        elements.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}"/>')
    elements.append("</svg>")
    return ("\n".join(elements) + "\n").encode("utf-8")


def render_poster(genre_index: int, family_index: int) -> bytes:
    minimal = (genre_index + family_index) % 2 == 0
    index = genre_index // 2 + family_index // 2
    count = 1 + index % 3 if minimal else 4 + index % 4
    circles = [
        (x, y, 27 + 4 * ((position + genre_index + family_index) % 5))
        for position, (x, y) in enumerate(LAYOUTS[family_index][:count])
    ]
    circles.extend(((600, 93, 7 + genre_index % 3), (625, 93, 11)))
    return svg_document(circles, COLORS[genre_index], BACKGROUNDS[genre_index])


def style_for_count(count: int) -> str:
    if count == 0:
        return REVIEW
    return MINIMAL if count <= 3 else DETAILED


def inspect_svg(content: bytes) -> tuple[int | None, str, str]:
    """Count visible supported circles using the saved SVG, without using record metadata."""
    root = ET.fromstring(content)
    if (
        root.tag != SVG + "svg"
        or root.get("viewBox") != f"0 0 {SIZE} {SIZE}"
        or root.get("width") != str(SIZE)
        or root.get("height") != str(SIZE)
    ):
        return None, REVIEW, "Неподдерживаемое поле SVG"

    circles = []
    for node in root:
        if node.tag == SVG + "rect":
            continue
        if node.tag != SVG + "circle" or set(node.attrib) != {"cx", "cy", "r", "fill"}:
            return None, REVIEW, "Неподдерживаемая фигура или оформление SVG"
        if node.attrib["fill"] not in COLORS:
            return None, REVIEW, "Цвет фигуры вне палитры"
        x, y, radius = (float(node.attrib[key]) for key in ("cx", "cy", "r"))
        if not all(math.isfinite(value) for value in (x, y, radius)) or radius <= 0:
            return None, REVIEW, "Некорректная геометрия круга"
        if radius >= MIN_RADIUS:
            circles.append((x, y, radius))

    for x, y, radius in circles:
        if min(x, y, SIZE - x, SIZE - y) < radius:
            return None, REVIEW, "Крупный круг обрезан краем"
    for index, (x, y, radius) in enumerate(circles):
        for other_x, other_y, other_radius in circles[index + 1 :]:
            if math.hypot(x - other_x, y - other_y) < radius + other_radius:
                return None, REVIEW, "Крупные круги перекрываются"

    count = len(circles)
    note = "Полные крупные круги, мелкие точки пропущены" if count else "Нет крупных кругов"
    return count, style_for_count(count), note


def geometry_sha256(content: bytes) -> str:
    """Fingerprint visible geometry without color, text or circle ordering."""
    root = ET.fromstring(content)
    circles = sorted(
        tuple(float(node.attrib[key]) for key in ("cx", "cy", "r"))
        for node in root.findall(SVG + "circle")
    )
    return hashlib.sha256(repr(circles).encode("utf-8")).hexdigest()
