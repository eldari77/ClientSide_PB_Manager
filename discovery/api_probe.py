"""Probe Space Engineers API surface and compare it with the virtual PB harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


API_SURFACE_SCHEMA = "novali.client_side_pb.se_api_surface.v1"
HARNESS_ALIGNMENT_SCHEMA = "novali.client_side_pb.harness_alignment.v1"
HARNESS_UPDATE_PLAN_SCHEMA = "novali.client_side_pb.harness_update_plan.v1"


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default or {}
    return payload if isinstance(payload, dict) else default or {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def probe_api_surface_from_source(
    source: str,
    *,
    source_name: str = "source",
    assembly_version: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_source(source)
    return {
        "schema": API_SURFACE_SCHEMA,
        "generated_at": generated_at or utc_now(),
        "source": source_name,
        "assembly_version": assembly_version,
        "api_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "interfaces": parse_interfaces(normalized),
        "enums": parse_enums(normalized),
    }


def normalize_source(source: str) -> str:
    return re.sub(r"\s+", " ", strip_comments(source)).strip()


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", source)


def parse_interfaces(source: str) -> dict[str, Any]:
    interfaces: dict[str, Any] = {}
    for match in re.finditer(r"public\s+interface\s+(IMy[A-Za-z0-9_]+)\b[^{]*\{", source):
        name = match.group(1)
        body, _ = balanced_body(source, match.end() - 1)
        interfaces[name] = {
            "properties": parse_properties(body),
            "methods": parse_methods(body),
        }
    return dict(sorted(interfaces.items()))


def parse_properties(body: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    pattern = re.compile(
        r"\b(?P<type>[A-Za-z0-9_.<>,\[\]?]+(?:\.[A-Za-z0-9_]+)*)\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{\s*get\s*;\s*(?P<set>set\s*;)?\s*\}"
    )
    for match in pattern.finditer(body):
        properties[match.group("name")] = {
            "type": match.group("type"),
            "can_write": bool(match.group("set")),
        }
    return dict(sorted(properties.items()))


def parse_methods(body: str) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    pattern = re.compile(
        r"\b(?P<return>[A-Za-z0-9_.<>,\[\]?]+(?:\.[A-Za-z0-9_]+)*)\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<params>[^)]*)\)\s*;"
    )
    for match in pattern.finditer(body):
        if "{" in match.group(0):
            continue
        name = match.group("name")
        if name in methods:
            overloads = methods[name].setdefault("overloads", [])
            overloads.append(method_payload(match))
            continue
        methods[name] = method_payload(match)
    return dict(sorted(methods.items()))


def method_payload(match: re.Match[str]) -> dict[str, Any]:
    return {
        "return_type": match.group("return"),
        "parameters": parse_parameters(match.group("params")),
    }


def parse_parameters(text: str) -> list[dict[str, str]]:
    parameters: list[dict[str, str]] = []
    for raw in split_parameters(text):
        param = raw.strip()
        if not param:
            continue
        param = param.split("=", 1)[0].strip()
        parts = param.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        parameters.append({"type": parts[0].strip(), "name": parts[1].strip()})
    return parameters


def split_parameters(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "<([":
            depth += 1
        elif char in ">)]" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def parse_enums(source: str) -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    for match in re.finditer(r"public\s+enum\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([^}]*)\}", source, flags=re.DOTALL):
        values: list[str] = []
        for raw in match.group(2).split(","):
            value = raw.strip().split("=", 1)[0].strip()
            if value:
                values.append(value)
        enums[match.group(1)] = values
    return dict(sorted(enums.items()))


def balanced_body(source: str, open_brace: int) -> tuple[str, int]:
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace + 1 : index], index
    return source[open_brace + 1 :], len(source)


def align_api_surface_with_harness(api_surface: dict[str, Any], harness: dict[str, Any]) -> dict[str, Any]:
    implemented = set(as_strings(harness.get("implemented_interfaces")))
    snapshot_fields = set(as_strings(harness.get("snapshot_fields")))
    mapped_properties = set(as_strings(harness.get("mapped_command_properties")))
    client_overlay_properties = set(as_strings(harness.get("client_overlay_properties")))
    read_supported_members = set(as_strings(harness.get("read_supported_members")))
    blocked_properties = set(as_strings(harness.get("blocked_command_properties")))
    command_kinds = set(as_strings(harness.get("available_command_kinds")))
    partial_features = set(as_strings(harness.get("partial_traversal_features")))

    supported: list[str] = []
    missing_read_stub: list[str] = []
    mutation_requires_command_mapping: list[str] = []
    blocked_for_safety: list[str] = []
    partial_traversal: list[str] = []

    interfaces = api_surface.get("interfaces") if isinstance(api_surface.get("interfaces"), dict) else {}
    for interface_name, interface in sorted(interfaces.items()):
        if interface_name not in implemented:
            missing_read_stub.append(interface_name)
            continue
        properties = interface.get("properties") if isinstance(interface.get("properties"), dict) else {}
        for property_name, detail in sorted(properties.items()):
            member = f"{interface_name}.{property_name}"
            if member in blocked_properties or property_name in blocked_properties:
                blocked_for_safety.append(member)
            elif member in read_supported_members or property_name in read_supported_members:
                supported.append(member)
            elif member in client_overlay_properties or property_name in client_overlay_properties:
                supported.append(member)
            elif bool((detail or {}).get("can_write")) and property_name not in mapped_properties and member not in mapped_properties:
                mutation_requires_command_mapping.append(member)
            elif snapshot_field_for_property(property_name) in snapshot_fields:
                supported.append(member)
            else:
                missing_read_stub.append(member)

        methods = interface.get("methods") if isinstance(interface.get("methods"), dict) else {}
        for method_name in sorted(methods):
            member = f"{interface_name}.{method_name}"
            if member in blocked_properties or method_name in blocked_properties:
                blocked_for_safety.append(member)
            elif member in read_supported_members or method_name in read_supported_members:
                supported.append(member)
            elif method_name == "WriteText" and "write_text_surface" in command_kinds:
                supported.append(member)
            elif method_name == "DrawFrame" and "text_surface_sprites" in partial_features:
                partial_traversal.append(member)
            elif is_read_style_method(method_name):
                missing_read_stub.append(member)
            else:
                mutation_requires_command_mapping.append(member)

    summary = {
        "supported": len(supported),
        "missing_read_stub": len(missing_read_stub),
        "mutation_requires_command_mapping": len(mutation_requires_command_mapping),
        "blocked_for_safety": len(blocked_for_safety),
        "partial_traversal": len(partial_traversal),
    }
    return {
        "schema": HARNESS_ALIGNMENT_SCHEMA,
        "generated_at": utc_now(),
        "api_hash": str(api_surface.get("api_hash", "") or ""),
        "harness_capability_version": str(harness.get("capability_version", "") or ""),
        "operator_status": operator_status_for_alignment(summary),
        "summary": summary,
        "supported": sorted(supported),
        "missing_read_stub": sorted(missing_read_stub),
        "mutation_requires_command_mapping": sorted(mutation_requires_command_mapping),
        "blocked_for_safety": sorted(blocked_for_safety),
        "partial_traversal": sorted(partial_traversal),
    }


def build_harness_update_plan(api_surface: dict[str, Any], alignment: dict[str, Any], *, max_items: int = 25) -> dict[str, Any]:
    read_only = [
        describe_member_for_plan(api_surface, member, "read_only_stub")
        for member in as_strings(alignment.get("missing_read_stub"))
        if is_read_only_plan_member(api_surface, member)
    ]
    mapping = [
        describe_member_for_plan(api_surface, member, "mapping_review")
        for member in as_strings(alignment.get("mutation_requires_command_mapping"))
    ]
    blocked = [
        describe_member_for_plan(api_surface, member, "blocked_for_safety")
        for member in as_strings(alignment.get("blocked_for_safety"))
    ]
    read_only = sorted((item for item in read_only if item), key=plan_sort_key)[:max_items]
    mapping = sorted((item for item in mapping if item), key=plan_sort_key)[:max_items]
    blocked = sorted((item for item in blocked if item), key=plan_sort_key)[:max_items]
    if read_only:
        operator_status = "read_only_stubs_ready"
        next_action = "add_read_only_stubs"
    elif mapping:
        operator_status = "mapping_review_ready"
        next_action = "review_command_mappings"
    elif blocked:
        operator_status = "blocked_review_only"
        next_action = "keep_blocked_until_design_review"
    else:
        operator_status = "aligned"
        next_action = "none"
    return {
        "schema": HARNESS_UPDATE_PLAN_SCHEMA,
        "generated_at": utc_now(),
        "api_hash": str(api_surface.get("api_hash", "") or ""),
        "harness_capability_version": str(alignment.get("harness_capability_version", "") or ""),
        "operator_status": operator_status,
        "next_recommended_action": next_action,
        "summary": {
            "read_only_stub_queue": len(read_only),
            "mapping_review_queue": len(mapping),
            "blocked_for_safety_queue": len(blocked),
        },
        "read_only_stub_queue": read_only,
        "mapping_review_queue": mapping,
        "blocked_for_safety_queue": blocked,
    }


def is_read_only_plan_member(api_surface: dict[str, Any], member: str) -> bool:
    detail = member_detail(api_surface, member)
    if not detail:
        return False
    if detail["member_kind"] == "interface":
        return False
    if detail["member_kind"] == "property":
        return not bool(detail.get("can_write"))
    return is_read_style_method(str(detail.get("member_name", "")))


def describe_member_for_plan(api_surface: dict[str, Any], member: str, queue: str) -> dict[str, Any] | None:
    detail = member_detail(api_surface, member)
    if not detail:
        return {"member": member, "queue": queue, "priority": 90, "reason": "interface stub needed before members can be modeled"}
    priority = member_priority(member, queue)
    payload = {
        "member": member,
        "interface": detail["interface"],
        "member_name": detail["member_name"],
        "member_kind": detail["member_kind"],
        "priority": priority,
        "risk": member_risk(member, queue),
        "review_required": queue != "read_only_stub",
        "reason": reason_for_queue(queue),
    }
    if detail["member_kind"] == "property":
        payload["value_type"] = str(detail.get("type", ""))
        payload["snapshot_field"] = snapshot_field_for_member(member)
        payload["can_write"] = bool(detail.get("can_write"))
    elif detail["member_kind"] == "method":
        payload["return_type"] = str(detail.get("return_type", ""))
        payload["parameters"] = detail.get("parameters", [])
        payload["suggested_command_kind"] = suggested_command_kind(member)
    return payload


def member_detail(api_surface: dict[str, Any], member: str) -> dict[str, Any] | None:
    interfaces = api_surface.get("interfaces") if isinstance(api_surface.get("interfaces"), dict) else {}
    if "." not in member:
        if member in interfaces:
            return {"interface": member, "member": member, "member_name": member, "member_kind": "interface"}
        return None
    interface_name, member_name = member.split(".", 1)
    interface = interfaces.get(interface_name) if isinstance(interfaces.get(interface_name), dict) else {}
    properties = interface.get("properties") if isinstance(interface.get("properties"), dict) else {}
    if member_name in properties and isinstance(properties[member_name], dict):
        return {
            "interface": interface_name,
            "member": member,
            "member_name": member_name,
            "member_kind": "property",
            **properties[member_name],
        }
    methods = interface.get("methods") if isinstance(interface.get("methods"), dict) else {}
    if member_name in methods and isinstance(methods[member_name], dict):
        return {
            "interface": interface_name,
            "member": member,
            "member_name": member_name,
            "member_kind": "method",
            **methods[member_name],
        }
    return None


def member_priority(member: str, queue: str) -> int:
    base = 10 if queue == "read_only_stub" else 50 if queue == "mapping_review" else 80
    common_interfaces = [
        "IMyTerminalBlock",
        "IMyTextSurface",
        "IMyTextSurfaceProvider",
        "IMyDoor",
        "IMyInventory",
        "IMyProductionBlock",
        "IMyAssembler",
        "IMyGasTank",
        "IMyGasGenerator",
        "IMyPowerProducer",
        "IMySensorBlock",
        "IMyShipController",
        "IMyThrust",
    ]
    for offset, interface in enumerate(common_interfaces):
        if member.startswith(interface + ".") or member == interface:
            return base + offset
    return base + 30


def plan_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    return (int(item.get("priority", 100) or 100), str(item.get("member", "")))


def member_risk(member: str, queue: str) -> str:
    if queue == "read_only_stub":
        return "read_only"
    high_risk_terms = ("Warhead", "Thrust", "Gyro", "Motor", "Rotor", "Piston", "ShipController", "RemoteControl", "Inventory", "Assembler", "ProductionBlock")
    if any(term in member for term in high_risk_terms):
        return "high_risk_requires_review"
    return "standard_review"


def reason_for_queue(queue: str) -> str:
    if queue == "read_only_stub":
        return "read-only endpoint can be modeled with snapshot field plus virtual PB getter"
    if queue == "mapping_review":
        return "mutating endpoint needs an explicit reviewed bridge command mapping"
    return "endpoint is intentionally blocked until design review"


def suggested_command_kind(member: str) -> str:
    if "." not in member:
        return ""
    interface_name, member_name = member.split(".", 1)
    return f"review_{camel_to_snake(interface_name.replace('IMy', ''))}_{camel_to_snake(member_name)}"


def is_read_style_method(method_name: str) -> bool:
    return method_name.startswith(("Get", "Try", "Is", "Can", "Calculate", "Measure", "Read", "Has", "Search", "Find", "Contain", "TimeUntil"))


def snapshot_field_for_member(member: str) -> str:
    if "." not in member:
        return ""
    interface_name, property_name = member.split(".", 1)
    prefix = {
        "IMyDoor": "door",
        "IMyGasTank": "gas",
        "IMyGasGenerator": "gas",
        "IMyPowerProducer": "power",
        "IMyThrust": "thrust",
        "IMyBatteryBlock": "battery",
    }.get(interface_name, "")
    field = camel_to_snake(property_name)
    if prefix and not field.startswith(prefix + "_"):
        field = f"{prefix}_{field}"
    return f"grid_snapshot.blocks[].{field}"


def operator_status_for_alignment(summary: dict[str, int]) -> str:
    if summary.get("mutation_requires_command_mapping", 0) > 0:
        return "needs_mapping_review"
    if summary.get("missing_read_stub", 0) > 0 or summary.get("partial_traversal", 0) > 0:
        return "needs_harness_update"
    return "aligned"


def snapshot_field_for_property(property_name: str) -> str:
    return f"grid_snapshot.blocks[].{camel_to_snake(property_name)}"


def camel_to_snake(value: str) -> str:
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.lower()


def as_strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def write_api_probe_reports(
    *,
    root: Path,
    source_path: Path,
    surface_output: Path,
    alignment_output: Path,
    plan_output: Path | None = None,
    harness_capabilities: dict[str, Any] | None = None,
    assembly_version: str = "",
    space_engineers_bin64: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    if space_engineers_bin64 is not None:
        reflected_source = root / "data" / "se_api_surface_source.cs"
        if generate_reflection_source(root, space_engineers_bin64, reflected_source):
            source_path = reflected_source
    source_path = source_path if source_path.is_absolute() else root / source_path
    surface_output = surface_output if surface_output.is_absolute() else root / surface_output
    alignment_output = alignment_output if alignment_output.is_absolute() else root / alignment_output
    plan_output = plan_output if plan_output and plan_output.is_absolute() else (root / plan_output if plan_output else root / "data" / "harness_update_plan.json")
    source = source_path.read_text(encoding="utf-8-sig")
    surface = probe_api_surface_from_source(source, source_name=str(source_path), assembly_version=assembly_version)
    harness = harness_capabilities or load_harness_capabilities(root)
    alignment = align_api_surface_with_harness(surface, harness)
    plan = build_harness_update_plan(surface, alignment)
    write_json(surface_output, surface)
    write_json(alignment_output, alignment)
    write_json(plan_output, plan)
    return surface, alignment, plan


def generate_reflection_source(root: Path, space_engineers_bin64: Path, output_source: Path) -> bool:
    script = root / "tools" / "probe_se_api_surface.ps1"
    if not script.exists() or not space_engineers_bin64.exists():
        return False
    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-ProjectRoot",
            str(root),
            "-SpaceEngineersBin64",
            str(space_engineers_bin64),
            "-OutputSource",
            str(output_source),
        ],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    return completed.returncode == 0 and output_source.exists()


def load_harness_capabilities(root: Path) -> dict[str, Any]:
    data_path = root / "data" / "virtual_pb_capabilities.json"
    payload = read_json(data_path)
    if payload:
        return payload
    output = root / "data" / "virtual_pb_capabilities.json"
    try:
        completed = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(root / "virtual_pb_runner" / "NOVALI.VirtualPBRunner.csproj"),
                "--",
                "--mode",
                "capabilities",
                "--output",
                str(output),
            ],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    return read_json(output)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe SE API surface and align it with the virtual PB harness.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--source", type=Path, default=Path("virtual_pb_runner/Program.cs"))
    parser.add_argument("--output", type=Path, default=Path("data/se_api_surface.json"))
    parser.add_argument("--alignment-output", type=Path, default=Path("data/harness_alignment.json"))
    parser.add_argument("--plan-output", type=Path, default=Path("data/harness_update_plan.json"))
    parser.add_argument("--assembly-version", default="")
    parser.add_argument("--space-engineers-bin64", type=Path, default=None, help="Optional SE Bin64 folder to reflect before parsing.")
    args = parser.parse_args()
    surface, alignment, plan = write_api_probe_reports(
        root=args.root,
        source_path=args.source,
        surface_output=args.output,
        alignment_output=args.alignment_output,
        plan_output=args.plan_output,
        assembly_version=args.assembly_version,
        space_engineers_bin64=args.space_engineers_bin64,
    )
    print(json.dumps({"surface": surface, "alignment": alignment, "plan": plan}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
