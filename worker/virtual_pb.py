from __future__ import annotations

import json
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


def analyze_virtual_pb_script(script_path: Path) -> dict[str, Any]:
    try:
        source = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "missing", "unsupported_apis": [], "error": type(exc).__name__}
    unsupported = sorted(label for pattern, label in UNSAFE_PATTERNS.items() if pattern in source)
    supported_block_types = sorted(
        block_type
        for block_type in [
            "IMyDoor",
            "IMyAirtightHangarDoor",
            "IMyLightingBlock",
            "IMySoundBlock",
            "IMyTextSurface",
        ]
        if block_type in source
    )
    return {
        "status": "unsupported" if unsupported else "supported",
        "unsupported_apis": unsupported,
        "supported_block_types": supported_block_types,
        "uses_grid_terminal_system": "GridTerminalSystem" in source,
        "uses_runtime": "Runtime." in source,
        "uses_custom_data": "CustomData" in source,
    }


def run_virtual_pb(script_path: Path, request: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    compatibility = analyze_virtual_pb_script(script_path)
    if compatibility["status"] != "supported":
        return {
            "adapter_status": "rejected",
            "summary": "Virtual PB script rejected by compatibility analysis.",
            "commands": [{"kind": "echo", "text": "virtual PB rejected: unsupported API"}],
            "compatibility": compatibility,
            "error_bucket": "virtual_pb_unsupported_api",
        }

    active_root = (root or Path(".")).resolve()
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
    payload.setdefault("compatibility", compatibility)
    payload.setdefault("summary", "Virtual PB tick processed.")
    payload.setdefault("commands", [])
    return payload
