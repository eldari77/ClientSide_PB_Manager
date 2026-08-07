from pathlib import Path

from workshop.scan_workshop import appworkshop_items, classify_workshop_item, fetch_steam_workshop_titles, iter_workshop_records, parse_vdf


def test_parse_vdf_nested_object():
    parsed = parse_vdf('"root" { "child" { "path" "C:\\\\Steam" } }')
    assert parsed["root"]["child"]["path"] == "C:\\Steam"


def test_classify_root_script_as_pb_script(tmp_path: Path):
    item = tmp_path / "123"
    item.mkdir()
    (item / "Script.cs").write_text("// Title: Demo\n", encoding="utf-8")
    kind, source, compatibility = classify_workshop_item(item)
    assert kind == "pb_script"
    assert source == item / "Script.cs"
    assert compatibility == "manual_adapter_required"


def test_classify_data_scripts_as_mod_script(tmp_path: Path):
    item = tmp_path / "123"
    scripts = item / "Data" / "Scripts" / "Mod"
    scripts.mkdir(parents=True)
    (scripts / "Session.cs").write_text("// mod", encoding="utf-8")
    kind, source, compatibility = classify_workshop_item(item)
    assert kind == "mod_script"
    assert source is None
    assert compatibility == "unsupported"


def test_appworkshop_items_and_record_scan(tmp_path: Path):
    steam = tmp_path / "Steam"
    steamapps = steam / "steamapps"
    workshop = steamapps / "workshop"
    content = workshop / "content" / "244850" / "42"
    content.mkdir(parents=True)
    (content / "script.cs").write_text("// Demo Script\n", encoding="utf-8")
    (steamapps / "libraryfolders.vdf").write_text('"libraryfolders" { "0" { "path" "' + str(steam).replace("\\", "\\\\") + '" } }', encoding="utf-8")
    (workshop / "appworkshop_244850.acf").write_text(
        '"AppWorkshop" { "WorkshopItemsInstalled" { "42" { "timeupdated" "1700000000" } } }',
        encoding="utf-8",
    )
    items = appworkshop_items(steam)
    assert "42" in items
    records = list(iter_workshop_records(steam, workshop_titles={"42": "Human Demo Name"}))
    assert len(records) == 1
    assert records[0].workshop_id == "42"
    assert records[0].workshop_title == "Human Demo Name"
    assert records[0].title_source == "steam"
    assert records[0].detected_kind == "pb_script"
    assert records[0].source_hash


def test_fetch_steam_workshop_titles_handles_network_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    assert fetch_steam_workshop_titles(["42"]) == {}
