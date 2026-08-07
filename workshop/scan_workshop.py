from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SPACE_ENGINEERS_APP_ID = "244850"
CATALOG_SCHEMA = "novali.client_side_pb.workshop_catalog.v1"


@dataclass
class WorkshopCatalogRecord:
    workshop_id: str
    workshop_title: str
    source_path: str
    source_hash: str
    steam_library: str
    time_updated: str
    detected_title: str
    detected_kind: str
    compatibility: str
    selected_bridge_id: str = ""
    notes: str = ""
    title_source: str = "fallback"


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}]', text)
    index = 0

    def unquote(token: str) -> str:
        return bytes(token[1:-1], "utf-8").decode("unicode_escape")

    def parse_object() -> dict[str, Any]:
        nonlocal index
        result: dict[str, Any] = {}
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                index += 1
                return result
            if token == "{":
                raise ValueError("Unexpected object start in VDF")
            key = unquote(token)
            index += 1
            if index >= len(tokens):
                result[key] = ""
                return result
            value = tokens[index]
            if value == "{":
                index += 1
                result[key] = parse_object()
            elif value == "}":
                result[key] = ""
            else:
                result[key] = unquote(value)
                index += 1
        return result

    parsed = parse_object()
    return parsed


def default_steam_root() -> Path:
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    return Path(program_files_x86) / "Steam"


def steam_libraries(steam_root: Path | None = None) -> list[Path]:
    root = steam_root or default_steam_root()
    library_file = root / "steamapps" / "libraryfolders.vdf"
    libraries = [root]
    if not library_file.exists():
        return libraries
    parsed = parse_vdf(library_file.read_text(encoding="utf-8", errors="replace"))
    folders = parsed.get("libraryfolders", {})
    if not isinstance(folders, dict):
        return libraries
    for value in folders.values():
        if not isinstance(value, dict):
            continue
        path_text = value.get("path")
        if not path_text:
            continue
        path = Path(path_text)
        if path not in libraries:
            libraries.append(path)
    return libraries


def appworkshop_items(library: Path) -> dict[str, dict[str, str]]:
    workshop_file = library / "steamapps" / "workshop" / f"appworkshop_{SPACE_ENGINEERS_APP_ID}.acf"
    if not workshop_file.exists():
        return {}
    parsed = parse_vdf(workshop_file.read_text(encoding="utf-8", errors="replace"))
    items = parsed.get("AppWorkshop", {}).get("WorkshopItemsInstalled", {})
    if not isinstance(items, dict):
        return {}
    return {str(item_id): value for item_id, value in items.items() if isinstance(value, dict)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def script_title(script_path: Path, workshop_id: str) -> str:
    try:
        for line in script_path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            stripped = line.strip(" /\t")
            if not stripped:
                continue
            if stripped.lower().startswith("title:"):
                return stripped.split(":", 1)[1].strip() or workshop_id
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or workshop_id
            if stripped.startswith("//"):
                text = stripped[2:].strip()
                if text and len(text) <= 100:
                    return text
    except OSError:
        pass
    return f"Workshop {workshop_id}"


def classify_workshop_item(item_dir: Path) -> tuple[str, Path | None, str]:
    root_scripts = [item_dir / "Script.cs", item_dir / "script.cs"]
    for script in root_scripts:
        if script.exists() and script.is_file():
            return "pb_script", script, "manual_adapter_required"

    if (item_dir / "bp.sbc").exists():
        return "blueprint", None, "unsupported"

    data_scripts = item_dir / "Data" / "Scripts"
    if data_scripts.exists():
        return "mod_script", None, "unsupported"

    return "unknown", None, "unsupported"


def fetch_steam_workshop_titles(workshop_ids: Iterable[str], batch_size: int = 100, timeout_seconds: float = 10.0) -> dict[str, str]:
    ids = [workshop_id for workshop_id in workshop_ids if workshop_id.isdigit()]
    titles: dict[str, str] = {}
    endpoint = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        form: dict[str, str] = {"itemcount": str(len(batch))}
        for index, workshop_id in enumerate(batch):
            form[f"publishedfileids[{index}]"] = workshop_id
        try:
            data = urllib.parse.urlencode(form).encode("utf-8")
            request = urllib.request.Request(endpoint, data=data, method="POST")
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            continue
        details = payload.get("response", {}).get("publishedfiledetails", [])
        if not isinstance(details, list):
            continue
        for detail in details:
            if not isinstance(detail, dict):
                continue
            workshop_id = str(detail.get("publishedfileid", ""))
            title = str(detail.get("title", "")).strip()
            if workshop_id and title:
                titles[workshop_id] = title
    return titles


def iter_workshop_records(steam_root: Path | None = None, workshop_titles: dict[str, str] | None = None) -> Iterable[WorkshopCatalogRecord]:
    workshop_titles = workshop_titles or {}
    for library in steam_libraries(steam_root):
        content_root = library / "steamapps" / "workshop" / "content" / SPACE_ENGINEERS_APP_ID
        installed = appworkshop_items(library)
        candidate_ids = set(installed.keys())
        if content_root.exists():
            candidate_ids.update(path.name for path in content_root.iterdir() if path.is_dir())
        for workshop_id in sorted(candidate_ids, key=lambda text: int(text) if text.isdigit() else text):
            item_dir = content_root / workshop_id
            detected_kind, source, compatibility = classify_workshop_item(item_dir) if item_dir.exists() else ("unknown", None, "unsupported")
            item_meta = installed.get(workshop_id, {})
            time_updated = item_meta.get("timeupdated", "")
            if time_updated.isdigit():
                time_updated = datetime.fromtimestamp(int(time_updated), tz=timezone.utc).isoformat()
            source_path = str(source) if source else str(item_dir)
            source_hash = sha256_file(source) if source and source.exists() else ""
            detected_title = script_title(source, workshop_id) if source else f"Workshop {workshop_id}"
            workshop_title = workshop_titles.get(workshop_id, "")
            display_title = workshop_title or detected_title
            yield WorkshopCatalogRecord(
                workshop_id=workshop_id,
                workshop_title=display_title,
                source_path=source_path,
                source_hash=source_hash,
                steam_library=str(library),
                time_updated=time_updated,
                detected_title=detected_title,
                detected_kind=detected_kind,
                compatibility=compatibility,
                title_source="steam" if workshop_title else "local",
            )


def write_catalog(records: list[WorkshopCatalogRecord], output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": CATALOG_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": [asdict(record) for record in records],
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def import_candidate(record: WorkshopCatalogRecord, imports_root: Path) -> Path:
    if record.detected_kind != "pb_script":
        raise ValueError(f"Only pb_script records can be imported, got {record.detected_kind}")
    source = Path(record.source_path)
    if not source.exists():
        raise FileNotFoundError(source)
    target_dir = imports_root / record.workshop_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "Script.cs"
    shutil.copy2(source, target)
    (target_dir / "metadata.json").write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan subscribed Space Engineers Workshop PB scripts.")
    parser.add_argument("--steam-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("data/workshop_catalog.json"))
    parser.add_argument("--no-steam-details", action="store_true", help="Skip Steam title lookup and use local fallback titles only.")
    args = parser.parse_args()

    title_map: dict[str, str] = {}
    if not args.no_steam_details:
        ids: set[str] = set()
        for library in steam_libraries(args.steam_root):
            ids.update(appworkshop_items(library).keys())
            content_root = library / "steamapps" / "workshop" / "content" / SPACE_ENGINEERS_APP_ID
            if content_root.exists():
                ids.update(path.name for path in content_root.iterdir() if path.is_dir())
        title_map = fetch_steam_workshop_titles(ids)

    records = list(iter_workshop_records(args.steam_root, workshop_titles=title_map))
    payload = write_catalog(records, args.output)
    pb_count = sum(1 for record in records if record.detected_kind == "pb_script")
    print(json.dumps({"output": str(args.output), "records": len(records), "pb_scripts": pb_count, "steam_titles": len(title_map), "schema": payload["schema"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
