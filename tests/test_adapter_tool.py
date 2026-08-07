import json
from pathlib import Path

from workshop.adapter_tool import prepare_adapter, safe_module_name


def test_safe_module_name_prefixes_numeric_id():
    assert safe_module_name("123") == "workshop_123_adapter"


def test_prepare_adapter_creates_scaffold_and_manifest(tmp_path: Path):
    root = tmp_path
    source_dir = root / "steam" / "123"
    source_dir.mkdir(parents=True)
    source = source_dir / "Script.cs"
    source.write_text("public void Main(string argument) {}\n", encoding="utf-8")
    catalog = root / "data" / "workshop_catalog.json"
    catalog.parent.mkdir()
    catalog.write_text(
        json.dumps(
            {
                "schema": "novali.client_side_pb.workshop_catalog.v1",
                "records": [
                    {
                        "workshop_id": "123",
                        "workshop_title": "Demo PB",
                        "source_path": str(source),
                        "detected_kind": "pb_script",
                        "compatibility": "manual_adapter_required",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    worker = root / "worker"
    (worker / "scripts").mkdir(parents=True)
    (worker / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (worker / "manifest.json").write_text('{"schema":"x","scripts":[]}', encoding="utf-8")

    report = prepare_adapter(root, catalog, "123")
    assert report["status"] == "adapter_scaffold_created"
    assert (root / "data" / "imports" / "123" / "Script.cs").exists()
    assert (root / "worker" / "scripts" / "workshop_123_adapter.py").exists()
    manifest = json.loads((root / "worker" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scripts"][0]["script_id"] == "workshop_123_adapter"
    assert manifest["scripts"][0]["enabled"] is False
    updated_catalog = json.loads(catalog.read_text(encoding="utf-8"))
    assert updated_catalog["records"][0]["compatibility"] == "adapter_scaffold_created"

