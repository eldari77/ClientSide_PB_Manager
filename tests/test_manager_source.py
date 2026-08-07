from pathlib import Path


MANAGER = Path("manager/MainWindow.xaml.cs")


def test_manager_mentions_orchestrator_and_virtual_pb_status():
    source = MANAGER.read_text(encoding="utf-8")

    assert "bridge_orchestrator" in source
    assert "child_worker_scripts" in source
    assert "virtual_pb_compatibility" in source


def test_manager_has_worker_ui_launcher():
    xaml = Path("manager/MainWindow.xaml").read_text(encoding="utf-8")
    source = MANAGER.read_text(encoding="utf-8")

    assert "Open Worker UI" in xaml
    assert "OpenWorkerUi_Click" in xaml
    assert "http://localhost:8788" in source
    assert "tools\\open_worker_ui.ps1" in source


def test_worker_ui_powershell_launcher_exists():
    script = Path("tools/open_worker_ui.ps1")
    source = script.read_text(encoding="utf-8")

    assert "docker compose up --build -d client-side-pb-worker" in source
    assert "http://localhost:8788" in source
    assert "[switch]$NoOpen" in source
