from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "novali.client_side_pb.worker_config.v1"


@dataclass
class ConfigEntry:
    key: str
    value: Any
    value_type: str
    description: str


DECLARATION = re.compile(
    r"^(?:const\s+)?(?P<type>string|bool|int|double)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?);"
)
STRING_ARRAY = re.compile(
    r"^string\[\]\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{(?P<value>.*?)\};"
)
STRING_LIST_START = re.compile(
    r"^List<\s*String\s*>\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*new\s+List<string>\s*\{"
)


def parse_scalar(value_type: str, raw_value: str) -> Any:
    raw_value = raw_value.strip()
    if value_type == "string":
        return parse_string(raw_value)
    if value_type == "bool":
        return raw_value.lower() == "true"
    if value_type == "int":
        try:
            return int(raw_value)
        except ValueError:
            return 0
    if value_type == "double":
        try:
            return float(raw_value)
        except ValueError:
            return 0.0
    return raw_value


def parse_string(raw_value: str) -> str:
    match = re.match(r'^"(.*)"$', raw_value.strip())
    if not match:
        return raw_value.strip()
    return match.group(1).replace('\\"', '"').replace("\\\\", "\\")


def parse_string_list(raw_value: str) -> list[str]:
    return [parse_string(match.group(0)) for match in re.finditer(r'"(?:\\.|[^"])*"', raw_value)]


def clean_comment(line: str) -> str:
    return line.strip().lstrip("/").strip()


def extract_config(source: Path, script_id: str, display_name: str) -> dict[str, Any]:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[ConfigEntry] = []
    comments: list[str] = []
    in_list_name = ""
    list_values: list[str] = []
    list_comments = ""

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("//"):
            comment = clean_comment(line)
            if comment and not comment.startswith("=") and not comment.startswith("---"):
                comments.append(comment)
            continue
        if not line:
            continue

        if in_list_name:
            if "};" in line:
                entries.append(ConfigEntry(in_list_name, list_values, "string_list", list_comments))
                in_list_name = ""
                list_values = []
                list_comments = ""
                comments = []
                continue
            if not line.startswith("//"):
                list_values.extend(parse_string_list(line))
            continue

        array_match = STRING_ARRAY.match(line)
        if array_match:
            entries.append(
                ConfigEntry(
                    array_match.group("name"),
                    parse_string_list(array_match.group("value")),
                    "string_list",
                    " ".join(comments[-3:]),
                )
            )
            comments = []
            continue

        list_match = STRING_LIST_START.match(line)
        if list_match:
            in_list_name = list_match.group("name")
            list_values = []
            list_comments = " ".join(comments[-3:])
            comments = []
            continue

        match = DECLARATION.match(line)
        if match:
            value_type = match.group("type")
            entries.append(
                ConfigEntry(
                    match.group("name"),
                    parse_scalar(value_type, match.group("value")),
                    "float" if value_type == "double" else value_type,
                    " ".join(comments[-3:]),
                )
            )
            comments = []

    return {
        "schema": SCHEMA,
        "script_id": script_id,
        "display_name": display_name,
        "source": str(source),
        "entries": [
            {
                "key": entry.key,
                "value": entry.value,
                "value_type": entry.value_type,
                "description": entry.description,
            }
            for entry in entries
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract operator config from an imported PB script.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--script-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = extract_config(args.source, args.script_id, args.display_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"entries": len(payload["entries"]), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
