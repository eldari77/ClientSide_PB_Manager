from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


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
            return {
                "status": "unsupported",
                "compiled": False,
                "unsupported_apis": ["runner_unavailable"],
                "unsupported_interfaces": [],
                "unsupported_members": ["runner_unavailable"],
                "blocked_members": [],
                "blocked_command_mappings": [],
                "missing_types": [],
                "missing_members": [],
                "compile_errors": [],
                "error_bucket": "virtual_pb_runner_unavailable",
                "runner_unavailable": True,
                "runner_stdout": completed.stdout[-1000:],
                "runner_stderr": completed.stderr[-1000:],
            }

    return {
        "status": "unsupported",
        "compiled": False,
        "unsupported_apis": ["runner_unavailable"],
        "unsupported_interfaces": [],
        "unsupported_members": ["runner_unavailable"],
        "blocked_members": [],
        "blocked_command_mappings": [],
        "missing_types": [],
        "missing_members": [],
        "compile_errors": [],
        "supported_block_types": [],
        "runner_unavailable": True,
        "error_bucket": "virtual_pb_runner_unavailable",
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
        completed = run_virtual_pb_runner_process(project, script_path, request_path, output_path, active_root)
        if completed.returncode != 0 or not output_path.exists():
            completed = run_virtual_pb_runner_process(project, script_path, request_path, output_path, active_root)
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


def run_virtual_pb_runner_process(
    project: Path,
    script_path: Path,
    request_path: Path,
    output_path: Path,
    active_root: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
        timeout=60,
        check=False,
    )
