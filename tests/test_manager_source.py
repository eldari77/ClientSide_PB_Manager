from pathlib import Path


MANAGER = Path("manager/MainWindow.xaml.cs")


def test_manager_mentions_orchestrator_and_virtual_pb_status():
    source = MANAGER.read_text(encoding="utf-8")

    assert "bridge_orchestrator" in source
    assert "child_worker_scripts" in source
    assert "virtual_pb_compatibility" in source
