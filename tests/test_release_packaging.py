from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_beta_package_script_defines_private_handoff_layout():
    script = read_text("tools/package_beta_release.ps1")

    assert "LICENSE.md" in script
    assert "README-START-HERE.md" in script
    assert "setup-guide.md" in script
    assert "safety-and-server-notes.md" in script
    assert "scripts\\install-or-update.ps1" in script
    assert "pb\\ClientSidePBBridgeShim.cs" in script
    assert "plugin\\NOVALI.ClientSidePBBridge.dll" in script
    assert "manager\\NOVALI.ClientSidePBManager.exe" in script
    assert "docker-compose.yml" in script
    assert "Compress-Archive" in script
    assert "__pycache__" in script
    assert "*.pyc" in script
    assert "data\\bridge_requests\\processed" not in script
    assert "data\\bridge_results\\pb-bridge-001.json" not in script


def test_beta_install_script_sets_up_local_only_dependencies():
    script = read_text("packaging/scripts/install-or-update.ps1")

    assert "$env:APPDATA\\Pulsar\\Legacy\\Local" in script
    assert "NOVALI.ClientSidePBBridge.dll" in script
    assert "Software\\Classes\\novali-client-side-pb-manager" in script
    assert "docker compose up --build -d" in script
    assert "data\\bridge_requests" in script
    assert "data\\bridge_results" in script


def test_beta_setup_guide_covers_nontechnical_handoff_steps():
    guide = read_text("docs/beta_handoff/setup-guide.md")

    required = [
        "Space Engineers",
        "Pulsar",
        "Docker Desktop",
        "install-or-update.ps1",
        "Copy PB Shim Script",
        "Copy PB CustomData",
        "Custom Data",
        "5-minute profile",
        "live server",
        "Troubleshooting",
    ]
    for text in required:
        assert text in guide


def test_beta_safety_notes_preserve_bridge_boundaries():
    notes = read_text("docs/beta_handoff/safety-and-server-notes.md")

    assert "local-only" in notes
    assert "no arbitrary PB C# execution" in notes
    assert "allowlisted command" in notes
    assert "pause" in notes
    assert "live server" in notes


def test_public_beta_license_is_source_available_not_open_source():
    license_text = read_text("LICENSE.md")
    license_lower = license_text.lower()

    assert "NOVALI Client-Side PB Bridge Proprietary Beta License" in license_text
    assert "All rights reserved" in license_text
    assert "not open source" in license_lower
    assert "view and download" in license_lower
    assert "Install and run" in license_text
    assert "Redistribute" in license_text
    assert "commercially exploit" in license_text
    assert "written permission" in license_text


def test_beta_docs_reference_public_repo_license():
    readme = read_text("README.md")
    start_here = read_text("docs/beta_handoff/README-START-HERE.md")
    safety = read_text("docs/beta_handoff/safety-and-server-notes.md")

    for text in (readme, start_here, safety):
        assert "LICENSE.md" in text
        assert "not open source" in text
