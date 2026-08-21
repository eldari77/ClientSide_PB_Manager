from __future__ import annotations

from typing import Any


def block_contains_keyword(block: dict[str, Any], keyword: str) -> bool:
    lowered = str(keyword or "").strip().lower()
    if not lowered:
        return False
    return lowered in str(block.get("name", "")).lower() or lowered in str(block.get("custom_data", "")).lower()


def blocks_matching_keyword(blocks: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    return [block for block in blocks if block_contains_keyword(block, keyword)]


def first_block_matching_keyword(blocks: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    for block in blocks:
        if block_contains_keyword(block, keyword):
            return block
    return None


def surface_index_for_custom_data_tag(block: dict[str, Any], keyword: str) -> int:
    lowered = str(keyword or "").strip().lower()
    if not lowered:
        return 0
    for raw_line in str(block.get("custom_data", "")).splitlines():
        line = raw_line.strip()
        if not line.startswith("@") or lowered not in line.lower():
            continue
        token = line.split(None, 1)[0][1:]
        try:
            return max(0, int(token))
        except ValueError:
            return 0
    return 0
