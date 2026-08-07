from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


UNSAFE_PATTERNS = {
    "System.IO": "System.IO",
    "File.": "File.",
    "Directory.": "Directory.",
    "System.Net": "System.Net",
    "HttpClient": "HttpClient",
    "Process.": "Process.",
    "System.Diagnostics": "System.Diagnostics",
    "Thread": "Thread",
    "Task.": "Task.",
    "Reflection": "Reflection",
    "Activator.": "Activator.",
    "Marshal.": "Marshal.",
}

SUPPORTED_INTERFACES = {
    "IMyAirtightHangarDoor",
    "IMyDoor",
    "IMyLightingBlock",
    "IMyGridTerminalSystem",
    "IMyProgrammableBlock",
    "IMySoundBlock",
    "IMyTerminalBlock",
    "IMyTextSurface",
}

IMY_IDENTIFIER = re.compile(r"\bIMy[A-Za-z0-9_]+\b")
UNSUPPORTED_MEMBER_PATTERNS = {
    "IMyTerminalBlock.ApplyAction": re.compile(r"\.ApplyAction\s*\("),
    "IMyTerminalBlock.SetValue": re.compile(r"\.SetValue(?:<[^>]+>)?\s*\("),
}


def analyze_virtual_pb_script(script_path: Path, root: Path | None = None) -> dict[str, Any]:
    active_root = (root or Path(".")).resolve()
    project = active_root / "virtual_pb_runner" / "NOVALI.VirtualPBRunner.csproj"
    if project.exists():
        with tempfile.TemporaryDirectory(prefix="novali-virtual-pb-analyze-") as temp_dir:
            output_path = Path(temp_dir) / "compatibility.json"
            try:
                completed = subprocess.run(
                    [
                        "dotnet",
                        "run",
                        "--project",
                        str(project),
                        "--",
                        "--mode",
                        "analyze",
                        "--script",
                        str(script_path),
                        "--output",
                        str(output_path),
                    ],
                    cwd=str(active_root),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {
                    "status": "unsupported",
                    "compiled": False,
                    "unsupported_apis": ["compile_timeout"],
                    "unsupported_interfaces": [],
                    "unsupported_members": ["compile_timeout"],
                    "error_bucket": "virtual_pb_compile_timeout",
                }
            if completed.returncode == 0 and output_path.exists():
                payload = json.loads(output_path.read_text(encoding="utf-8-sig"))
                payload.setdefault("runner_stdout", completed.stdout[-1000:])
                return payload

    try:
        source = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "missing", "unsupported_apis": [], "unsupported_interfaces": [], "unsupported_members": [], "error": type(exc).__name__}
    unsafe_matches = sorted(label for pattern, label in UNSAFE_PATTERNS.items() if pattern in source)
    referenced_interfaces = set(IMY_IDENTIFIER.findall(source))
    unsupported_interfaces = sorted(referenced_interfaces - SUPPORTED_INTERFACES)
    unsupported_members = sorted(f"unsupported_member:{name}" for name, pattern in UNSUPPORTED_MEMBER_PATTERNS.items() if pattern.search(source))
    unsupported = (
        unsafe_matches
        + [f"unsupported_interface:{name}" for name in unsupported_interfaces]
        + unsupported_members
    )
    supported_block_types = sorted(
        block_type
        for block_type in SUPPORTED_INTERFACES
        if block_type in source
    )
    return {
        "status": "unsupported" if unsupported else "supported",
        "compiled": False,
        "unsupported_apis": unsupported,
        "unsupported_interfaces": unsupported_interfaces,
        "unsupported_members": unsupported_members,
        "supported_block_types": supported_block_types,
        "uses_grid_terminal_system": "GridTerminalSystem" in source,
        "uses_runtime": "Runtime." in source,
        "uses_custom_data": "CustomData" in source,
    }


def run_virtual_pb(script_path: Path, request: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    active_root = (root or Path(".")).resolve()
    compatibility = analyze_virtual_pb_script(script_path, active_root)
    if compatibility["status"] != "supported":
        return {
            "adapter_status": "rejected",
            "summary": "Virtual PB script rejected by compatibility analysis.",
            "commands": [{"kind": "echo", "text": "virtual PB rejected: unsupported API"}],
            "compatibility": compatibility,
            "error_bucket": "virtual_pb_unsupported_api",
        }

    project = active_root / "virtual_pb_runner" / "NOVALI.VirtualPBRunner.csproj"
    if not project.exists():
        return {
            "adapter_status": "failed",
            "summary": "Virtual PB runner project is missing.",
            "commands": [{"kind": "echo", "text": "virtual PB runner missing"}],
            "compatibility": compatibility,
            "error_bucket": "virtual_pb_runner_missing",
        }

    with tempfile.TemporaryDirectory(prefix="novali-virtual-pb-") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        output_path = Path(temp_dir) / "output.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(project),
                "--",
                "--script",
                str(script_path),
                "--request",
                str(request_path),
                "--output",
                str(output_path),
            ],
            cwd=str(active_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0 or not output_path.exists():
            return {
                "adapter_status": "failed",
                "summary": "Virtual PB runner failed.",
                "commands": [{"kind": "echo", "text": "virtual PB runner failed"}],
                "compatibility": compatibility,
                "error_bucket": "virtual_pb_runner_failed",
                "runner_stdout": completed.stdout[-1000:],
                "runner_stderr": completed.stderr[-1000:],
            }
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    generated_compatibility = payload.get("compatibility") if isinstance(payload.get("compatibility"), dict) else {}
    merged_compatibility = dict(generated_compatibility)
    for key, value in compatibility.items():
        if key not in {"status", "compiled"} or key not in merged_compatibility:
            merged_compatibility[key] = value
    for key, value in generated_compatibility.items():
        if key in {"status", "compiled", "emitted_command_kinds"}:
            merged_compatibility[key] = value
    payload["compatibility"] = merged_compatibility
    payload.setdefault("summary", "Virtual PB tick processed.")
    payload.setdefault("commands", [])
    return payload
