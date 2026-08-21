import json
import subprocess
from pathlib import Path

from worker.worker import save_virtual_pb_compatibility_report
from worker.virtual_pb import analyze_virtual_pb_script, run_virtual_pb


def test_virtual_pb_analysis_rejects_unsafe_apis(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
using System.IO;
public Program() {}
public void Main(string argument) { File.WriteAllText("x", "y"); }
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert "System.IO" in report["unsupported_apis"]
    assert "File." in report["unsupported_apis"]


def test_virtual_pb_analysis_rejects_unemulated_interfaces(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var modded = new List<IMyExperimentalJumpGate>();
    GridTerminalSystem.GetBlocksOfType(modded);
}
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert "IMyExperimentalJumpGate" in report["unsupported_interfaces"]
    assert "unsupported_interface:IMyExperimentalJumpGate" in report["unsupported_apis"]


def test_virtual_pb_capabilities_mode_reports_harness_and_commands(tmp_path: Path):
    output = tmp_path / "capabilities.json"

    completed = subprocess.run(
        [
            "dotnet",
            "run",
            "--project",
            "virtual_pb_runner/NOVALI.VirtualPBRunner.csproj",
            "--",
            "--mode",
            "capabilities",
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "novali.client_side_pb.virtual_pb_capabilities.v1"
    assert "IMyTextPanel" in report["implemented_interfaces"]
    assert "write_text_surface" in report["available_command_kinds"]
    assert "grid_snapshot.blocks[].inventories[].items[]" in report["snapshot_fields"]
    assert "grid_snapshot.blocks[].surface_size" in report["snapshot_fields"]
    assert "grid_snapshot.blocks[].texture_size" in report["snapshot_fields"]
    assert "grid_snapshot.blocks[].font_size" in report["snapshot_fields"]
    assert "grid_snapshot.blocks[].custom_name_with_faction" in report["snapshot_fields"]
    assert "grid_snapshot.blocks[].terminal_actions[]" in report["snapshot_fields"]
    assert "grid_snapshot.blocks[].terminal_properties[]" in report["snapshot_fields"]
    assert "IMyTerminalBlock.GetActions" in report["read_supported_members"]
    assert "IMyTerminalBlock.GetActionWithName" in report["read_supported_members"]
    assert "IMyTerminalBlock.HasLocalPlayerAccess" in report["read_supported_members"]
    assert "ControlModule.AddInput" in report["client_overlay_properties"]
    assert "ThrustOverride" in report["blocked_command_properties"]
    assert "text_surface_sprites" in report["partial_traversal_features"]
    assert "named_block_groups" in report["partial_traversal_features"]


def test_virtual_pb_compiled_script_writes_text_panel_from_inventory_snapshot(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument, UpdateType updateSource)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels, p => p.CustomName.Contains("LCD"));
    var containers = new List<IMyCargoContainer>();
    GridTerminalSystem.GetBlocksOfType(containers);
    var items = new List<MyInventoryItem>();
    containers[0].GetInventory(0).GetItems(items);
    panels[0].WriteText(items[0].Type.SubtypeId + ":" + items[0].Amount.ToString(), false);
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 10,
        "script_id": "virtual_auto_lcd_fixture",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 301,
                    "name": "Main LCD",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "text": "",
                    "custom_data": "",
                    "inventories": [],
                },
                {
                    "entity_id": 401,
                    "name": "Cargo",
                    "same_construct": True,
                    "is_cargo": True,
                    "inventory_count": 1,
                    "inventories": [
                        {
                            "index": 0,
                            "current_volume": 1.0,
                            "max_volume": 10.0,
                            "items": [
                                {
                                    "type_id": "MyObjectBuilder_Ingot",
                                    "subtype_id": "Iron",
                                    "amount": 1200,
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["compiled"] is True
    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == [
        {
            "kind": "write_text_surface",
            "block_entity_id": 301,
            "surface_index": 0,
            "append": False,
            "text": "Iron:1200",
        }
    ]


def test_virtual_pb_terminal_block_read_stubs_use_snapshot_metadata(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var blocks = new List<IMyTerminalBlock>();
    GridTerminalSystem.GetBlocks(blocks);
    var block = blocks[0];
    var actions = new List<ITerminalAction>();
    block.GetActions(actions, action => action.Id.Contains("OnOff"));
    var properties = new List<ITerminalProperty>();
    block.GetProperties(properties, property => property.Id == "FontSize");
    var namedAction = block.GetActionWithName("Toggle Block");
    var namedProperty = block.GetProperty("FontSize");
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    panels[0].WriteText(
        block.CustomNameWithFaction + "|" +
        block.DetailedInfo + "|" +
        block.CustomInfo + "|" +
        block.HasLocalPlayerAccess().ToString() + "|" +
        block.HasPlayerAccess(123).ToString() + "|" +
        block.HasNobodyPlayerAccessToBlock().ToString() + "|" +
        block.HasPlayerAccessWithNobodyCheck(123).ToString() + "|" +
        actions[0].Id + "|" +
        namedAction.Id + "|" +
        properties[0].TypeName + "|" +
        namedProperty.Id,
        false);
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 11,
        "script_id": "virtual_terminal_read_fixture",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 301,
                    "name": "Main LCD",
                    "custom_name_with_faction": "[NOV] Main LCD",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "detailed_info": "Detailed snapshot",
                    "custom_info": "Custom info snapshot",
                    "has_local_player_access": True,
                    "has_player_access": True,
                    "has_nobody_player_access": False,
                    "has_player_access_with_nobody_check": True,
                    "terminal_actions": [
                        {"id": "OnOff_On", "name": "Toggle Block"},
                        {"id": "ShowInTerminal", "name": "Show in Terminal"},
                    ],
                    "terminal_properties": [
                        {"id": "FontSize", "type": "Single"},
                        {"id": "OnOff", "type": "Boolean"},
                    ],
                }
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"][0]["text"] == (
        "[NOV] Main LCD|Detailed snapshot|Custom info snapshot|True|True|False|True|"
        "OnOff_On|OnOff_On|Single|FontSize"
    )


def test_virtual_pb_invokes_workshop_style_non_public_main(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
void Main(string argument, UpdateType updateSource)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    panels[0].WriteText("non-public main ran", false);
}
""",
        encoding="utf-8",
    )

    result = run_virtual_pb(
        script,
        {"grid_snapshot": {"blocks": [{"entity_id": 77, "name": "PB LCD", "is_lcd": True, "surface_count": 1}]}},
    )

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"][0]["text"] == "non-public main ran"


def test_virtual_pb_gap_miner_reports_missing_types_and_members(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    MissingTelemetryType value = null;
    Echo(value.Name);
}
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert report["compiled"] is False
    assert "MissingTelemetryType" in report["missing_types"]
    assert any("MissingTelemetryType" in error for error in report["compile_errors"])


def test_virtual_pb_compiled_script_reads_assembler_queue_and_inventory_definition(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var assemblers = new List<IMyAssembler>();
    GridTerminalSystem.GetBlocksOfType(assemblers);
    var queue = new List<MyProductionItem>();
    assemblers[0].GetQueue(queue);
    MyDefinitionId queued = queue[0].BlueprintId;
    MyAssemblerMode mode = assemblers[0].Mode;

    var containers = new List<IMyCargoContainer>();
    GridTerminalSystem.GetBlocksOfType(containers);
    var items = new List<MyInventoryItem>();
    containers[0].GetInventory(0).GetItems(items);
    MyDefinitionId inventoryType = items[0].Type;

    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    panels[0].WriteText(mode + ":" + queue[0].Amount + ":" + queued.SubtypeId + ":" + inventoryType.SubtypeId, false);
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 11,
        "script_id": "virtual_isy_fixture",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 301,
                    "name": "Inventory LCD",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "text": "",
                    "custom_data": "",
                },
                {
                    "entity_id": 401,
                    "name": "Main Assembler",
                    "same_construct": True,
                    "is_assembler": True,
                    "assembler_mode": "assembly",
                    "production_queue": [
                        {
                            "blueprint_id": "MyObjectBuilder_BlueprintDefinition/SteelPlate",
                            "amount": 42,
                        }
                    ],
                },
                {
                    "entity_id": 501,
                    "name": "Cargo",
                    "same_construct": True,
                    "is_cargo": True,
                    "inventory_count": 1,
                    "inventories": [
                        {
                            "index": 0,
                            "items": [
                                {
                                    "type_id": "MyObjectBuilder_Ingot",
                                    "subtype_id": "Iron",
                                    "amount": 1200,
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == [
        {
            "kind": "write_text_surface",
            "block_entity_id": 301,
            "surface_index": 0,
            "append": False,
            "text": "Assembly:42:SteelPlate:Iron",
        }
    ]


def test_virtual_pb_supports_isy_style_read_helpers_and_stringbuilder_text(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() { Storage = "seen=true"; }
public void Main(string argument)
{
    MyDefinitionId parsed;
    MyDefinitionId.TryParse("MyObjectBuilder_Ingot/Iron", out parsed);
    MyDefinitionId itemId = MyItemType.MakeIngot("Iron");

    var containers = new List<IMyCargoContainer>();
    GridTerminalSystem.GetBlocksOfType(containers);
    var inventory = containers[0].GetInventory(0);
    var found = inventory.FindItem(MyItemType.MakeIngot("Iron"));
    bool canAdd = inventory.CanItemsBeAdded(1, MyItemType.MakeOre("Stone"));
    bool connected = inventory.IsConnectedTo(inventory);
    double amount = (double)inventory.GetItemAmount(MyItemType.MakeIngot("Iron"));

    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    var text = new StringBuilder();
    text.Append(parsed.TypeId).Append(":").Append(parsed.SubtypeName).Append(":");
    text.Append(itemId == parsed).Append(":").Append(found.HasValue).Append(":");
    text.Append(canAdd).Append(":").Append(connected).Append(":").Append(amount).Append(":").Append(Storage);
    panels[0].WriteText(text, false);
}
""",
        encoding="utf-8",
    )
    request = {
        "grid_snapshot": {
            "blocks": [
                {"entity_id": 10, "name": "Status LCD", "is_lcd": True, "surface_count": 1},
                {
                    "entity_id": 20,
                    "name": "Cargo",
                    "is_cargo": True,
                    "inventory_count": 1,
                    "inventories": [
                        {
                            "items": [
                                {
                                    "type_id": "MyObjectBuilder_Ingot",
                                    "subtype_id": "Iron",
                                    "amount": 12,
                                }
                            ]
                        }
                    ],
                },
            ]
        }
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"][0]["text"] == "MyObjectBuilder_Ingot:Iron:True:True:True:True:12:seen=true"


def test_virtual_pb_can_select_blocks_by_custom_data(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public void Main(string argument)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels, panel => panel.CustomData.Contains("IIM-inventory"));
    panels[0].WriteText(panels[0].CustomData.Split('\\n')[1], false);
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 11,
        "script_id": "virtual_custom_data_selector_fixture",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 301,
                    "name": "LCD Panel Ore",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "text": "",
                    "custom_data": "@0 IIM-inventory\nOre 1000000",
                },
                {
                    "entity_id": 302,
                    "name": "LCD Panel Main",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "text": "",
                    "custom_data": "@0 IIM-main",
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == [
        {
            "kind": "write_text_surface",
            "block_entity_id": 301,
            "surface_index": 0,
            "append": False,
            "text": "Ore 1000000",
        }
    ]


def test_virtual_pb_preserves_text_surface_geometry_and_style_commands(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public void Main(string argument)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    panels[0].Font = "Monospace";
    panels[0].FontSize = 0.42f;
    panels[0].TextPadding = 1.5f;
    panels[0].Alignment = TextAlignment.CENTER;
    panels[0].ContentType = ContentType.TEXT_AND_IMAGE;
    Vector2 measured = panels[0].MeasureStringInPixels(new StringBuilder("12345"), panels[0].Font, panels[0].FontSize);
    panels[0].WriteText(panels[0].SurfaceSize.X + "x" + panels[0].TextureSize.Y + ":" + measured.X, false);
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 11,
        "script_id": "virtual_surface_style_fixture",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 401,
                    "name": "Adaptive LCD",
                    "same_construct": True,
                    "is_lcd": True,
                    "surface_count": 1,
                    "surface_size": {"x": 384, "y": 192},
                    "texture_size": {"x": 512, "y": 512},
                    "font": "Debug",
                    "font_size": 0.8,
                    "text_padding": 4,
                    "alignment": "RIGHT",
                    "content_type": "TEXT_AND_IMAGE",
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"][0]["block_entity_id"] == 401
    assert result["commands"][0]["text"].startswith("384x512:")
    assert result["commands"][0]["font"] == "Monospace"
    assert result["commands"][0]["font_size"] == 0.42
    assert result["commands"][0]["text_padding"] == 1.5
    assert result["commands"][0]["alignment"] == "CENTER"
    assert result["commands"][0]["content_type"] == "TEXT_AND_IMAGE"


def test_virtual_pb_preserves_text_surface_provider_index(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public void Main(string argument)
{
    var providers = new List<IMyTextSurfaceProvider>();
    GridTerminalSystem.GetBlocksOfType(providers);
    providers[0].GetSurface(1).WriteText("surface one", false);
}
""",
        encoding="utf-8",
    )
    request = {
        "grid_snapshot": {
            "blocks": [
                {"entity_id": 501, "name": "Cockpit LCDs", "is_lcd": True, "surface_count": 2},
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"][0]["surface_index"] == 1


def test_virtual_pb_compiles_assembler_queue_mutators_but_blocks_execution(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var assemblers = new List<IMyAssembler>();
    GridTerminalSystem.GetBlocksOfType(assemblers);
    assemblers[0].ClearQueue();
    assemblers[0].AddQueueItem(MyDefinitionId.Parse("MyObjectBuilder_BlueprintDefinition/SteelPlate"), 1);
}
""",
        encoding="utf-8",
    )

    result = run_virtual_pb(
        script,
        {
            "grid_snapshot": {
                "blocks": [
                    {"entity_id": 30, "name": "Assembler", "is_assembler": True},
                ]
            }
        },
    )

    assert result["compatibility"]["compiled"] is True
    assert result["compatibility"]["status"] == "blocked_command_mapping"
    assert "IMyAssembler.ClearQueue" in result["compatibility"]["blocked_command_mappings"]
    assert result["error_bucket"] == "virtual_pb_unsupported_api"


def test_virtual_pb_allows_client_overlay_setvalue_without_commands(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    Me.SetValue<string>("ControlModule.AddInput", "MoveX");
    Me.SetValue<bool>("ControlModule.RunOnInput", true);
    Me.SetValue<float>("ControlModule.RepeatDelay", 0.016f);
    var inputs = Me.GetValue<Dictionary<string, object>>("ControlModule.Inputs");
    Echo(inputs.Count.ToString());
}
""",
        encoding="utf-8",
    )

    result = run_virtual_pb(script, {"grid_snapshot": {"blocks": []}})

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == []


def test_virtual_pb_supports_sprite_math_surface_helpers(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    var rect = new RectangleF((panels[0].TextureSize - panels[0].SurfaceSize) / 2f, panels[0].SurfaceSize);
    var direction = Base6Directions.GetDirection(new Vector3I(0, 1, 0));
    var flipped = Base6Directions.GetFlippedDirection(direction);
    var clamped = MathHelper.Clamp(rect.Width, 0, 512);
    panels[0].ContentType = ContentType.SCRIPT;
    panels[0].ScriptBackgroundColor = Color.Black;
    using (var frame = panels[0].DrawFrame())
    {
        frame.Add(MySprite.CreateSprite("SquareSimple", rect.Position, new Vector2(clamped, 10)));
        frame.Add(MySprite.CreateText(flipped.ToString(), "Debug", Color.White, 1f, TextAlignment.CENTER));
    }
}
""",
        encoding="utf-8",
    )

    result = run_virtual_pb(
        script,
        {"grid_snapshot": {"blocks": [{"entity_id": 40, "name": "HUD LCD", "is_lcd": True, "surface_count": 1}]}},
    )

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == []


def test_virtual_pb_supports_whip_display_and_custom_data_overlay_shapes(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var lights = new List<IMyLightingBlock>();
    GridTerminalSystem.GetBlocksOfType(lights);
    lights[0].BlinkIntervalSeconds = 1.5f;
    lights[0].BlinkLength = 75f;
    lights[0].CustomData = "[Door]\\nOpen=true";

    var ini = new MyIni();
    ini.EndContent = Me.CustomData;

    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    using (var frame = panels[0].DrawFrame())
    {
        frame.Add(new MySprite(
            SpriteType.TEXTURE,
            "SquareSimple",
            new Vector2(10, 10),
            new Vector2(20, 20),
            Color.Red,
            null,
            TextAlignment.CENTER));
        frame.Add(new MySprite(
            SpriteType.TEXT,
            "NOVALI",
            new Vector2(5, 5),
            null,
            Color.White,
            "Debug",
            TextAlignment.CENTER,
            0.8f));
    }
}
""",
        encoding="utf-8",
    )

    result = run_virtual_pb(
        script,
        {
            "script_id": "virtual_whip_shape_fixture",
            "grid_snapshot": {
                "blocks": [
                    {"entity_id": 40, "name": "Door Status LCD", "is_lcd": True, "surface_count": 1},
                    {"entity_id": 50, "name": "Door Status Light", "is_light": True, "custom_data": ""},
                ]
            },
        },
    )

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"] == []
    assert result["compatibility"]["client_overlay_writes"]


def test_virtual_pb_seeds_me_custom_data_before_program_constructor(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
string constructorCustomData = "";
public Program()
{
    constructorCustomData = Me.CustomData;
}
public void Main(string argument)
{
    var panels = new List<IMyTextPanel>();
    GridTerminalSystem.GetBlocksOfType(panels);
    panels[0].WriteText(constructorCustomData);
}
""",
        encoding="utf-8",
    )

    result = run_virtual_pb(
        script,
        {
            "script_id": "virtual_custom_data_fixture",
            "virtual_pb": {
                "custom_data": "station_mode;\nitemID;blueprintID\nMyObjectBuilder_Component/SteelPlate;MyObjectBuilder_BlueprintDefinition/sdx_itemsBlueprintT0SteelPlate"
            },
            "grid_snapshot": {
                "blocks": [
                    {"entity_id": 40, "name": "PB LCD", "is_lcd": True, "surface_count": 1},
                ]
            },
        },
    )

    assert result["compatibility"]["status"] == "supported"
    assert result["commands"][0]["kind"] == "write_text_surface"
    assert result["commands"][0]["text"].startswith("station_mode;")
    assert "sdx_itemsBlueprintT0SteelPlate" in result["commands"][0]["text"]


def test_virtual_pb_imported_whip_script_compiles_when_present():
    script = Path("data/imports/416932930/Script.cs")
    if not script.exists():
        return

    report = analyze_virtual_pb_script(script)

    assert report["compiled"] is True
    assert report["status"] == "supported"
    assert "IMyLightingBlock.BlinkIntervalSeconds" not in report["missing_members"]
    assert "IMyLightingBlock.BlinkLength" not in report["missing_members"]
    assert "MyIni.EndContent" not in report["missing_members"]


def test_virtual_pb_blocks_unknown_setvalue_with_mapping_report(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    Me.SetValue<float>("Dangerous.Property", 1f);
}
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "blocked_command_mapping"
    assert "Dangerous.Property" in report["blocked_command_mappings"]
    assert "unsupported_member:IMyTerminalBlock.SetValue:Dangerous.Property" in report["blocked_members"]


def test_virtual_pb_rejects_unmapped_generic_terminal_mutation(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
public Program() {}
public void Main(string argument)
{
    var blocks = new List<IMyTerminalBlock>();
    GridTerminalSystem.GetBlocksOfType(blocks);
    blocks[0].ApplyAction("OnOff_On");
}
""",
        encoding="utf-8",
    )

    report = analyze_virtual_pb_script(script)

    assert report["status"] == "unsupported"
    assert "unsupported_member:IMyTerminalBlock.ApplyAction" in report["unsupported_members"]


def test_virtual_pb_fixture_closes_open_door_and_sets_light(tmp_path: Path):
    script = tmp_path / "Script.cs"
    script.write_text(
        """
const string Tag = "Airlock";
public Program() {}
public void Main(string argument)
{
    var doors = new List<IMyDoor>();
    GridTerminalSystem.GetBlocksOfType(doors, d => d.CustomName.Contains(Tag));
    foreach (var door in doors)
    {
        if (door.OpenRatio > 0.9f)
        {
            door.CloseDoor();
        }
    }
    var lights = new List<IMyLightingBlock>();
    GridTerminalSystem.GetBlocksOfType(lights, l => l.CustomName.Contains(Tag));
    foreach (var light in lights)
    {
        light.Enabled = true;
        light.Color = new Color(255, 40, 40);
    }
}
""",
        encoding="utf-8",
    )
    request = {
        "bridge_id": "bridge-virtual",
        "sequence": 9,
        "script_id": "virtual_whip_auto_door",
        "grid_snapshot": {
            "source": "plugin",
            "blocks": [
                {
                    "entity_id": 100,
                    "name": "A Airlock Interior",
                    "same_construct": True,
                    "is_door": True,
                    "door_open_ratio": 1.0,
                    "door_status": "Open",
                    "custom_data": "",
                },
                {
                    "entity_id": 200,
                    "name": "A Airlock Light",
                    "same_construct": True,
                    "is_light": True,
                    "enabled": False,
                    "color": {"r": 0, "g": 0, "b": 0, "a": 255},
                    "custom_data": "",
                },
            ],
        },
    }

    result = run_virtual_pb(script, request)

    assert result["compatibility"]["status"] == "supported"
    assert {"kind": "set_door_open", "block_entity_id": 100, "open": False} in result["commands"]
    assert {
        "kind": "set_light_color",
        "block_entity_id": 200,
        "color": {"r": 255, "g": 40, "b": 40, "a": 255},
    } in result["commands"]
    assert {"kind": "set_block_enabled", "block_entity_id": 200, "enabled": True} in result["commands"]


def test_virtual_pb_runner_project_exists():
    project = Path("virtual_pb_runner/NOVALI.VirtualPBRunner.csproj")
    assert project.exists()


def test_virtual_pb_compatibility_report_is_persisted(tmp_path: Path):
    save_virtual_pb_compatibility_report(
        tmp_path,
        "virtual_whip_auto_door",
        {
            "status": "supported",
            "compiled": True,
            "unsupported_apis": [],
            "unsupported_interfaces": [],
            "unsupported_members": [],
            "required_interfaces": ["IMyDoor"],
            "implemented_interfaces": ["IMyDoor", "IMyTextPanel"],
            "supported_block_types": ["IMyDoor"],
            "available_command_kinds": ["set_door_open", "write_text_surface"],
            "snapshot_requirements": ["grid_snapshot.blocks[].door_status"],
            "client_overlay_writes": [{"member": "IMyTerminalBlock.CustomData", "block_entity_id": 1}],
            "capability_categories": {"client_overlay": ["IMyTerminalBlock.CustomData"]},
            "capability_version": "dynamic-harness-test",
        },
        {"summary": "Virtual PB tick processed.", "commands": [{"kind": "set_door_open"}]},
    )

    report = json.loads((tmp_path / "data" / "virtual_pb_compatibility.json").read_text(encoding="utf-8"))

    assert report["scripts"]["virtual_whip_auto_door"]["compiled"] is True
    assert report["scripts"]["virtual_whip_auto_door"]["emitted_command_kinds"] == ["set_door_open"]
    assert report["scripts"]["virtual_whip_auto_door"]["required_interfaces"] == ["IMyDoor"]
    assert report["scripts"]["virtual_whip_auto_door"]["available_command_kinds"] == ["set_door_open", "write_text_surface"]
    assert report["scripts"]["virtual_whip_auto_door"]["snapshot_requirements"] == ["grid_snapshot.blocks[].door_status"]
    assert report["scripts"]["virtual_whip_auto_door"]["client_overlay_writes"][0]["member"] == "IMyTerminalBlock.CustomData"
    assert report["scripts"]["virtual_whip_auto_door"]["capability_categories"]["client_overlay"] == ["IMyTerminalBlock.CustomData"]
