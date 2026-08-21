from __future__ import annotations

import math
from typing import Any


DEFAULT_FONT = "Debug"
DEFAULT_FONT_SIZE = 0.6
DEFAULT_TEXT_PADDING = 2.0
MIN_FONT_SIZE = 0.35
MAX_FONT_SIZE = 1.2


def layout_text_for_surface(text: str, block: dict[str, Any], sequence: int = 0) -> dict[str, Any]:
    font_size = clamp_float(block.get("font_size"), DEFAULT_FONT_SIZE, MIN_FONT_SIZE, MAX_FONT_SIZE)
    padding = clamp_float(block.get("text_padding"), DEFAULT_TEXT_PADDING, 0.0, 20.0)
    width, height = surface_dimensions(block)
    wrapped = wrap_text_lines(str(text or "").splitlines(), width, font_size, padding)
    font_size, wrapped = shrink_until_reasonable(str(text or "").splitlines(), width, height, font_size, padding)
    visible_lines = max(1, int((height - padding * 2) / line_height(font_size)))
    scrolling = len(wrapped) > visible_lines
    if scrolling:
        max_offset = max(0, len(wrapped) - visible_lines)
        offset = int(sequence or 0) % (max_offset + 1)
        visible = wrapped[offset : offset + visible_lines]
    else:
        offset = 0
        visible = wrapped
    output_text = "\n".join(visible)
    if str(text or "").endswith("\n"):
        output_text += "\n"
    return {
        "text": output_text,
        "font": str(block.get("font") or DEFAULT_FONT),
        "font_size": round(font_size, 3),
        "text_padding": round(padding, 3),
        "alignment": str(block.get("alignment") or "LEFT"),
        "content_type": str(block.get("content_type") or "TEXT_AND_IMAGE"),
        "layout": {
            "surface_width": width,
            "surface_height": height,
            "wrapped_lines": len(wrapped),
            "visible_lines": visible_lines,
            "scrolling": scrolling,
            "scroll_offset": offset,
        },
    }


def shrink_until_reasonable(lines: list[str], width: float, height: float, font_size: float, padding: float) -> tuple[float, list[str]]:
    current = font_size
    wrapped = wrap_text_lines(lines, width, current, padding)
    while current > MIN_FONT_SIZE and len(wrapped) > max(1, int((height - padding * 2) / line_height(current))):
        next_size = max(MIN_FONT_SIZE, current - 0.05)
        if next_size == current:
            break
        current = next_size
        wrapped = wrap_text_lines(lines, width, current, padding)
    return current, wrapped


def wrap_text_lines(lines: list[str], width: float, font_size: float, padding: float) -> list[str]:
    max_chars = max(8, int((width - padding * 2) / char_width(font_size)))
    wrapped: list[str] = []
    for line in lines:
        if line == "":
            wrapped.append("")
            continue
        remaining = line
        while len(remaining) > max_chars:
            split_at = remaining.rfind(" ", 0, max_chars + 1)
            if split_at <= 0:
                split_at = max_chars
            wrapped.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        wrapped.append(remaining)
    return wrapped or [""]


def surface_dimensions(block: dict[str, Any]) -> tuple[float, float]:
    surface_size = block.get("surface_size") if isinstance(block.get("surface_size"), dict) else {}
    width = number_from(surface_size, "x", 512.0) or number_from(surface_size, "width", 512.0)
    height = number_from(surface_size, "y", 512.0) or number_from(surface_size, "height", 512.0)
    return max(64.0, width), max(64.0, height)


def char_width(font_size: float) -> float:
    return max(3.0, 9.0 * font_size)


def line_height(font_size: float) -> float:
    return max(8.0, 28.0 * font_size)


def clamp_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    if math.isnan(parsed) or math.isinf(parsed):
        parsed = fallback
    return min(max(parsed, minimum), maximum)


def number_from(source: dict[str, Any], key: str, fallback: float) -> float:
    try:
        return float(source.get(key, fallback))
    except (TypeError, ValueError):
        return fallback
