using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using Sandbox.ModAPI;
using VRage.Game.ModAPI;
using VRage.ModAPI;
using VRage.Plugins;

[assembly: AssemblyTitle("NOVALI Client-Side PB Bridge")]
[assembly: AssemblyDescription("Local adapter bridge for offloading PB planning work.")]
[assembly: AssemblyCompany("NOVALI")]
[assembly: AssemblyProduct("NOVALI Client-Side PB Bridge")]
[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.0")]

namespace NOVALI.ClientSidePBBridge
{
    public sealed class ClientSidePBBridgePlugin : IPlugin, IDisposable
    {
        private const string Schema = "novali.client_side_pb_bridge.v1";
        private const string Begin = "NOVALI_CLIENT_SIDE_PB_JSON_BEGIN";
        private const string End = "NOVALI_CLIENT_SIDE_PB_JSON_END";
        private const int PollEveryTicks = 60;
        private const int InventorySnapshotBlockCap = 300;
        private const int InventorySnapshotItemCap = 1200;
        private const int GridSnapshotBlockCap = 500;
        private const int ProductionQueueItemCap = 120;
        private int _tick;
        private string _root;
        private string _lastStatus = "starting";
        private int _lastEntityCount;
        private int _lastProgrammableBlockCandidates;
        private int _lastMarkedMailboxes;
        private int _stagedRequests;
        private int _returnedResults;
        private string _lastBridgeId = "";
        private int _lastSequence;
        private string _lastMailboxKind = "";
        private string _lastResultState = "";
        private int _lastInventorySnapshotBlocks;
        private int _lastInventorySnapshotItems;
        private string _lastInventorySnapshotState = "not_requested";
        private int _lastInventorySnapshotSkippedBlocks;
        private int _lastGridSnapshotBlocks;
        private int _lastGridSnapshotLcds;
        private int _lastGridSnapshotMachines;
        private string _lastGridSnapshotState = "not_requested";
        private int _lastGridSnapshotSkippedBlocks;
        private bool _lastGridSnapshotTruncatedBlocks;
        private string _lastGridSnapshotSkipSamples = "";
        private string _lastVisibleGridScanState = "not_seen";
        private int _lastVisibleGridScanBlocks;
        private int _lastVisibleGridScanMachines;
        private int _lastVisibleGridScanAssemblers;
        private int _lastVisibleGridScanActiveAssemblers;
        private int _lastVisibleGridScanFoodProcessors;
        private int _lastVisibleGridScanRefineries;
        private int _lastVisibleGridScanActiveRefineries;
        private string _lastVisibleGridScanProductionSummary = "";
        private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);
        private readonly Dictionary<string, int> _lastSequences = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        public void Init(object gameInstance)
        {
            _root = ResolveRoot();
            Directory.CreateDirectory(Path.Combine(_root, "data", "bridge_requests"));
            Directory.CreateDirectory(Path.Combine(_root, "data", "bridge_results"));
            WriteStatus("initialized");
        }

        public void Update()
        {
            _tick++;
            if (_tick % PollEveryTicks != 0)
            {
                return;
            }
            try
            {
                PumpMailboxes();
                WriteStatus("ok");
            }
            catch (Exception ex)
            {
                WriteStatus("safe_exception_" + ex.GetType().Name);
            }
        }

        public void Dispose()
        {
            WriteStatus("disposed");
        }

        private void PumpMailboxes()
        {
            if (MyAPIGateway.Entities == null)
            {
                return;
            }
            var entities = new HashSet<IMyEntity>();
            MyAPIGateway.Entities.GetEntities(entities);
            _lastEntityCount = entities.Count;
            _lastProgrammableBlockCandidates = 0;
            _lastMarkedMailboxes = 0;
            ResetVisibleGridStatus("no_marked_mailbox");
            foreach (var entity in entities)
            {
                if (entity == null)
                {
                    continue;
                }
                var grid = entity as IMyCubeGrid;
                if (grid != null)
                {
                    PumpGridMailboxes(grid);
                    continue;
                }
                PumpMailboxEntity(entity);
            }
        }

        private void PumpGridMailboxes(IMyCubeGrid grid)
        {
            var blocks = new List<IMySlimBlock>();
            try
            {
                grid.GetBlocks(blocks, block => block != null && block.FatBlock != null);
            }
            catch
            {
                return;
            }
            foreach (var block in blocks)
            {
                if (block == null || block.FatBlock == null)
                {
                    continue;
                }
                PumpMailboxEntity(block.FatBlock);
            }
        }

        private void PumpMailboxEntity(object entity)
        {
            if (entity == null)
            {
                return;
            }
                var typeName = entity.GetType().FullName ?? entity.GetType().Name;
                if (typeName.IndexOf("ProgrammableBlock", StringComparison.OrdinalIgnoreCase) < 0)
                {
                    return;
                }
                _lastProgrammableBlockCandidates++;
                var customData = ReadStringMember(entity, "CustomData");
                if (string.IsNullOrWhiteSpace(customData) || customData.IndexOf(Begin, StringComparison.OrdinalIgnoreCase) < 0)
                {
                    return;
                }
                _lastMarkedMailboxes++;
                var body = ExtractMarkedBody(customData);
                if (string.IsNullOrWhiteSpace(body))
                {
                    return;
                }
                RefreshVisibleGridStatus(entity);
                var messageKind = ExtractJsonString(body, "message_kind");
                _lastMailboxKind = messageKind;
                if (!string.Equals(messageKind, "request", StringComparison.OrdinalIgnoreCase))
                {
                    _lastResultState = "mailbox_kind_" + (string.IsNullOrWhiteSpace(messageKind) ? "missing" : messageKind);
                    return;
                }
                var bridgeId = ExtractJsonString(body, "bridge_id");
                var scriptId = ExtractJsonString(body, "script_id");
                var sequence = ExtractJsonInt(body, "sequence");
                if (string.IsNullOrWhiteSpace(bridgeId) || string.IsNullOrWhiteSpace(scriptId) || sequence <= 0)
                {
                    return;
                }
                var enrichedBody = EnrichRequestBody(body, entity);
                if (StageRequestIfNew(bridgeId, sequence, enrichedBody))
                {
                    _stagedRequests++;
                    _lastBridgeId = bridgeId;
                    _lastSequence = sequence;
                }
                if (ReturnResultIfPresent(entity, customData, bridgeId, sequence))
                {
                    _returnedResults++;
                    _lastBridgeId = bridgeId;
                    _lastSequence = sequence;
                }
        }

        private string EnrichRequestBody(string body, object programmableBlock)
        {
            var enriched = body;
            if (enriched.IndexOf("\"inventory_snapshot\"", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                _lastInventorySnapshotState = "already_present";
            }
            else
            {
                var snapshot = BuildInventorySnapshotJson(programmableBlock);
                if (!string.IsNullOrWhiteSpace(snapshot))
                {
                    enriched = AppendJsonProperty(enriched, "inventory_snapshot", snapshot, ref _lastInventorySnapshotState);
                }
            }

            if (enriched.IndexOf("\"grid_snapshot\"", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                _lastGridSnapshotState = "already_present";
            }
            else
            {
                var gridSnapshot = BuildGridSnapshotJson(programmableBlock);
                if (!string.IsNullOrWhiteSpace(gridSnapshot))
                {
                    enriched = AppendJsonProperty(enriched, "grid_snapshot", gridSnapshot, ref _lastGridSnapshotState);
                }
            }
            return enriched;
        }

        private string AppendJsonProperty(string body, string propertyName, string propertyJson, ref string state)
        {
            var trimmed = body.Trim();
            if (!trimmed.EndsWith("}", StringComparison.Ordinal))
            {
                state = "request_json_not_object";
                return body;
            }
            return trimmed.Substring(0, trimmed.Length - 1) + "," + Quote(propertyName) + ":" + propertyJson + "}";
        }

        private string BuildInventorySnapshotJson(object programmableBlock)
        {
            _lastInventorySnapshotBlocks = 0;
            _lastInventorySnapshotItems = 0;
            _lastInventorySnapshotSkippedBlocks = 0;
            try
            {
                var grid = ReadObjectMember(programmableBlock, "CubeGrid") as IMyCubeGrid;
                if (grid == null)
                {
                    _lastInventorySnapshotState = "pb_grid_missing";
                    return "";
                }
                var slimBlocks = new List<IMySlimBlock>();
                try
                {
                    grid.GetBlocks(slimBlocks, block => block != null && block.FatBlock != null);
                }
                catch
                {
                    var entities = new HashSet<IMyEntity>();
                    MyAPIGateway.Entities.GetEntities(entities);
                    foreach (var entity in entities)
                    {
                        var candidateGrid = entity as IMyCubeGrid;
                        if (candidateGrid == null)
                        {
                            continue;
                        }
                        try
                        {
                            candidateGrid.GetBlocks(slimBlocks, block => block != null && block.FatBlock != null);
                        }
                        catch
                        {
                        }
                    }
                }
                var builder = new StringBuilder();
                builder.Append("{");
                builder.Append(Quote("schema")).Append(":").Append(Quote("novali.client_side_pb.inventory_snapshot.v1")).Append(",");
                builder.Append(Quote("source")).Append(":").Append(Quote("plugin")).Append(",");
                builder.Append(Quote("block_cap")).Append(":").Append(InventorySnapshotBlockCap.ToString()).Append(",");
                builder.Append(Quote("item_cap")).Append(":").Append(InventorySnapshotItemCap.ToString()).Append(",");
                builder.Append(Quote("blocks")).Append(":[");
                var firstBlock = true;
                var truncatedBlocks = false;
                var truncatedItems = false;
                foreach (var slimBlock in slimBlocks)
                {
                    if (_lastInventorySnapshotBlocks >= InventorySnapshotBlockCap)
                    {
                        truncatedBlocks = true;
                        break;
                    }
                    if (slimBlock == null || slimBlock.FatBlock == null)
                    {
                        continue;
                    }
                    string blockJson;
                    try
                    {
                        blockJson = BuildInventoryBlockJson(slimBlock.FatBlock, ref truncatedItems);
                    }
                    catch
                    {
                        _lastInventorySnapshotSkippedBlocks++;
                        continue;
                    }
                    if (string.IsNullOrWhiteSpace(blockJson))
                    {
                        continue;
                    }
                    if (!firstBlock)
                    {
                        builder.Append(",");
                    }
                    firstBlock = false;
                    builder.Append(blockJson);
                    _lastInventorySnapshotBlocks++;
                    if (truncatedItems)
                    {
                        break;
                    }
                }
                builder.Append("],");
                builder.Append(Quote("truncated_blocks")).Append(":").Append(truncatedBlocks ? "true" : "false").Append(",");
                builder.Append(Quote("truncated_items")).Append(":").Append(truncatedItems ? "true" : "false");
                builder.Append("}");
                _lastInventorySnapshotState = _lastInventorySnapshotSkippedBlocks > 0 ? "ok_with_skips" : "ok";
                return builder.ToString();
            }
            catch (Exception ex)
            {
                _lastInventorySnapshotState = "snapshot_exception_" + ex.GetType().Name;
                return "";
            }
        }

        private string BuildInventoryBlockJson(object block, ref bool truncatedItems)
        {
            if (block == null)
            {
                return "";
            }
            var inventoryCount = ReadIntMember(block, "InventoryCount", 0);
            if (inventoryCount <= 0 && !ReadBoolMember(block, "HasInventory", false))
            {
                return "";
            }
            if (inventoryCount <= 0)
            {
                inventoryCount = 1;
            }
            var builder = new StringBuilder();
            builder.Append("{");
            builder.Append(Quote("entity_id")).Append(":").Append(ReadLongMember(block, "EntityId", 0).ToString()).Append(",");
            builder.Append(Quote("name")).Append(":").Append(Quote(ReadStringMember(block, "CustomName"))).Append(",");
            builder.Append(Quote("type")).Append(":").Append(Quote(BlockTypeName(block))).Append(",");
            builder.Append(Quote("subtype")).Append(":").Append(Quote(BlockSubtypeName(block))).Append(",");
            builder.Append(Quote("same_construct")).Append(":true,");
            builder.Append(Quote("inventories")).Append(":[");
            var firstInventory = true;
            for (var index = 0; index < inventoryCount; index++)
            {
                var inventory = ReadInventory(block, index);
                if (inventory == null)
                {
                    continue;
                }
                if (!firstInventory)
                {
                    builder.Append(",");
                }
                firstInventory = false;
                builder.Append(BuildInventoryJson(inventory, index, ref truncatedItems));
                if (truncatedItems)
                {
                    break;
                }
            }
            builder.Append("]}");
            return builder.ToString();
        }

        private string BuildGridSnapshotJson(object programmableBlock)
        {
            _lastGridSnapshotBlocks = 0;
            _lastGridSnapshotLcds = 0;
            _lastGridSnapshotMachines = 0;
            _lastGridSnapshotSkippedBlocks = 0;
            _lastGridSnapshotTruncatedBlocks = false;
            _lastGridSnapshotSkipSamples = "";
            try
            {
                var grid = ReadObjectMember(programmableBlock, "CubeGrid") as IMyCubeGrid;
                if (grid == null)
                {
                    _lastGridSnapshotState = "pb_grid_missing";
                    return "";
                }
                var slimBlocks = new List<IMySlimBlock>();
                grid.GetBlocks(slimBlocks, block => block != null && block.FatBlock != null);
                var builder = new StringBuilder();
                builder.Append("{");
                builder.Append(Quote("schema")).Append(":").Append(Quote("novali.client_side_pb.grid_snapshot.v1")).Append(",");
                builder.Append(Quote("source")).Append(":").Append(Quote("plugin")).Append(",");
                builder.Append(Quote("block_cap")).Append(":").Append(GridSnapshotBlockCap.ToString()).Append(",");
                builder.Append(Quote("blocks")).Append(":[");
                var firstBlock = true;
                foreach (var slimBlock in slimBlocks)
                {
                    if (_lastGridSnapshotBlocks >= GridSnapshotBlockCap)
                    {
                        _lastGridSnapshotTruncatedBlocks = true;
                        break;
                    }
                    if (slimBlock == null || slimBlock.FatBlock == null)
                    {
                        continue;
                    }
                    string blockJson;
                    try
                    {
                        blockJson = BuildGridBlockJson(slimBlock.FatBlock);
                    }
                    catch (Exception ex)
                    {
                        RecordGridSnapshotSkip(slimBlock.FatBlock, ex);
                        blockJson = BuildGridBlockFallbackJson(slimBlock.FatBlock);
                        if (string.IsNullOrWhiteSpace(blockJson))
                        {
                            continue;
                        }
                    }
                    if (string.IsNullOrWhiteSpace(blockJson))
                    {
                        continue;
                    }
                    if (!firstBlock)
                    {
                        builder.Append(",");
                    }
                    firstBlock = false;
                    builder.Append(blockJson);
                    _lastGridSnapshotBlocks++;
                }
                builder.Append("],");
                builder.Append(Quote("truncated_blocks")).Append(":").Append(_lastGridSnapshotTruncatedBlocks ? "true" : "false");
                builder.Append("}");
                _lastGridSnapshotState = _lastGridSnapshotSkippedBlocks > 0 ? "ok_with_skips" : "ok";
                return builder.ToString();
            }
            catch (Exception ex)
            {
                _lastGridSnapshotState = "snapshot_exception_" + ex.GetType().Name;
                return "";
            }
        }

        private void ResetVisibleGridStatus(string state)
        {
            _lastVisibleGridScanState = state;
            _lastVisibleGridScanBlocks = 0;
            _lastVisibleGridScanMachines = 0;
            _lastVisibleGridScanAssemblers = 0;
            _lastVisibleGridScanActiveAssemblers = 0;
            _lastVisibleGridScanFoodProcessors = 0;
            _lastVisibleGridScanRefineries = 0;
            _lastVisibleGridScanActiveRefineries = 0;
            _lastVisibleGridScanProductionSummary = "";
        }

        private void RefreshVisibleGridStatus(object programmableBlock)
        {
            ResetVisibleGridStatus("scanning");
            try
            {
                var grid = ReadObjectMember(programmableBlock, "CubeGrid") as IMyCubeGrid;
                if (grid == null)
                {
                    _lastVisibleGridScanState = "pb_grid_missing";
                    return;
                }
                var slimBlocks = new List<IMySlimBlock>();
                grid.GetBlocks(slimBlocks, block => block != null && block.FatBlock != null);
                foreach (var slimBlock in slimBlocks)
                {
                    if (slimBlock == null || slimBlock.FatBlock == null)
                    {
                        continue;
                    }
                    _lastVisibleGridScanBlocks++;
                    RefreshVisibleGridBlockStatus(slimBlock.FatBlock);
                }
                _lastVisibleGridScanState = "ok";
            }
            catch (Exception ex)
            {
                _lastVisibleGridScanState = "scan_exception_" + ex.GetType().Name;
            }
        }

        private void RefreshVisibleGridBlockStatus(object block)
        {
            var type = BlockTypeName(block);
            var subtype = BlockSubtypeName(block);
            var name = ReadStringMember(block, "CustomName");
            var typeKey = (type + " " + subtype + " " + block.GetType().FullName + " " + name).ToLowerInvariant();
            var isAssembler = ContainsAny(typeKey, "assembler");
            var isFoodProcessor = ContainsAny(typeKey, "foodprocessor", "food processor");
            var isRefinery = ContainsAny(typeKey, "refinery");
            var isGasGenerator = ContainsAny(typeKey, "oxygengenerator", "gasgenerator", "o2h2");
            var isReactor = ContainsAny(typeKey, "reactor");
            var isGasTank = ContainsAny(typeKey, "gastank", "oxygentank", "hydrogentank");
            if (!(isAssembler || isFoodProcessor || isRefinery || isGasGenerator || isReactor || isGasTank))
            {
                return;
            }
            _lastVisibleGridScanMachines++;
            var enabled = ReadBoolMember(block, "Enabled", true);
            var conveyor = ReadBoolMember(block, "UseConveyorSystem", ReadBoolMember(block, "UseConveyor", false));
            if (isFoodProcessor)
            {
                _lastVisibleGridScanFoodProcessors++;
                AppendVisibleGridProductionSummary("food", block, name, subtype, enabled, conveyor);
                return;
            }
            if (isAssembler)
            {
                _lastVisibleGridScanAssemblers++;
                if (enabled)
                {
                    _lastVisibleGridScanActiveAssemblers++;
                }
                AppendVisibleGridProductionSummary("assembler", block, name, subtype, enabled, conveyor);
                return;
            }
            if (isRefinery)
            {
                _lastVisibleGridScanRefineries++;
                if (enabled)
                {
                    _lastVisibleGridScanActiveRefineries++;
                }
                AppendVisibleGridProductionSummary("refinery", block, name, subtype, enabled, conveyor);
                return;
            }
            AppendVisibleGridProductionSummary("machine", block, name, subtype, enabled, conveyor);
        }

        private void AppendVisibleGridProductionSummary(string role, object block, string name, string subtype, bool enabled, bool conveyor)
        {
            if (_lastVisibleGridScanProductionSummary.Length > 1000)
            {
                return;
            }
            if (_lastVisibleGridScanProductionSummary.Length > 0)
            {
                _lastVisibleGridScanProductionSummary += "; ";
            }
            _lastVisibleGridScanProductionSummary += role +
                "|" + ReadLongMember(block, "EntityId", 0).ToString() +
                "|" + Limit(string.IsNullOrWhiteSpace(name) ? "<unnamed>" : name, 80) +
                "|subtype=" + Limit(subtype, 60) +
                "|enabled=" + (enabled ? "true" : "false") +
                "|conveyor=" + (conveyor ? "true" : "false");
        }

        private string BuildGridBlockJson(object block)
        {
            if (block == null)
            {
                return "";
            }
            var type = BlockTypeName(block);
            var subtype = BlockSubtypeName(block);
            var typeKey = (type + " " + subtype + " " + block.GetType().FullName).ToLowerInvariant();
            var isLcd = ContainsAny(typeKey, "textpanel", "textsurface", "lcd");
            var isAssembler = ContainsAny(typeKey, "assembler");
            var isFoodProcessor = ContainsAny(typeKey, "foodprocessor", "food processor") ||
                ContainsAny(ReadStringMember(block, "CustomName").ToLowerInvariant(), "foodprocessor", "food processor");
            var isRefinery = ContainsAny(typeKey, "refinery");
            var isGasGenerator = ContainsAny(typeKey, "oxygengenerator", "gasgenerator", "o2h2");
            var isReactor = ContainsAny(typeKey, "reactor");
            var isGasTank = ContainsAny(typeKey, "gastank", "oxygentank", "hydrogentank");
            var isConnector = ContainsAny(typeKey, "shipconnector", "connector");
            var isCargo = ContainsAny(typeKey, "cargo", "container");
            var isDoor = ContainsAny(typeKey, "door");
            var isHangarDoor = ContainsAny(typeKey, "hangardoor", "hangar door");
            var isLight = ContainsAny(typeKey, "lightingblock", "interiorlight", "reflectorlight", "light");
            var isSound = ContainsAny(typeKey, "soundblock", "sound block");
            var hasInventory = ReadBoolMember(block, "HasInventory", false) || ReadIntMember(block, "InventoryCount", 0) > 0;
            var isPbAdjacent = ContainsAny(typeKey, "programmableblock", "timerblock", "sensorblock", "buttonpanel");
            if (!(isLcd || isAssembler || isRefinery || isGasGenerator || isReactor || isGasTank || isConnector || isCargo || isDoor || isLight || isSound || isPbAdjacent || hasInventory))
            {
                return "";
            }
            if (isLcd)
            {
                _lastGridSnapshotLcds++;
            }
            if (isAssembler || isFoodProcessor || isRefinery || isGasGenerator || isReactor || isGasTank)
            {
                _lastGridSnapshotMachines++;
            }
            var inventoryCount = ReadIntMember(block, "InventoryCount", 0);
            if (inventoryCount <= 0 && hasInventory)
            {
                inventoryCount = 1;
            }
            var surfaceCount = Math.Max(ReadIntMember(block, "SurfaceCount", 0), isLcd ? 1 : 0);
            var builder = new StringBuilder();
            builder.Append("{");
            builder.Append(Quote("entity_id")).Append(":").Append(ReadLongMember(block, "EntityId", 0).ToString()).Append(",");
            builder.Append(Quote("name")).Append(":").Append(Quote(ReadStringMember(block, "CustomName"))).Append(",");
            builder.Append(Quote("type")).Append(":").Append(Quote(type)).Append(",");
            builder.Append(Quote("subtype")).Append(":").Append(Quote(subtype)).Append(",");
            builder.Append(Quote("same_construct")).Append(":true,");
            builder.Append(Quote("enabled")).Append(":").Append(ReadBoolMember(block, "Enabled", true) ? "true" : "false").Append(",");
            builder.Append(Quote("use_conveyor")).Append(":").Append(ReadBoolMember(block, "UseConveyorSystem", ReadBoolMember(block, "UseConveyor", false)) ? "true" : "false").Append(",");
            builder.Append(Quote("inventory_count")).Append(":").Append(inventoryCount.ToString()).Append(",");
            builder.Append(Quote("surface_count")).Append(":").Append(surfaceCount.ToString()).Append(",");
            builder.Append(Quote("text")).Append(":").Append(Quote(Limit(ReadSurfaceText(block), 600))).Append(",");
            builder.Append(Quote("custom_data")).Append(":").Append(Quote(Limit(ReadStringMember(block, "CustomData"), 600))).Append(",");
            builder.Append(Quote("assembler_mode")).Append(":").Append(Quote(ReadStringMember(block, "Mode"))).Append(",");
            builder.Append(Quote("assembler_cooperative_mode")).Append(":").Append(ReadBoolMember(block, "CooperativeMode", false) ? "true" : "false").Append(",");
            builder.Append(Quote("production_queue_count")).Append(":").Append(ReadIntMember(block, "QueueCount", 0).ToString()).Append(",");
            builder.Append(Quote("production_queue")).Append(":").Append(BuildProductionQueueJson(block)).Append(",");
            builder.Append(Quote("gas_auto_refill")).Append(":").Append(ReadGasAutoRefill(block) ? "true" : "false").Append(",");
            builder.Append(Quote("stockpile")).Append(":").Append(ReadBoolMember(block, "Stockpile", false) ? "true" : "false").Append(",");
            builder.Append(Quote("gas_filled_ratio")).Append(":").Append(FormatDouble(ReadDoubleLikeMember(block, "FilledRatio"))).Append(",");
            builder.Append(Quote("door_open_ratio")).Append(":").Append(FormatDouble(ReadDoubleLikeMember(block, "OpenRatio"))).Append(",");
            builder.Append(Quote("door_status")).Append(":").Append(Quote(ReadStringMember(block, "Status"))).Append(",");
            builder.Append(Quote("color")).Append(":").Append(ReadColorJson(block)).Append(",");
            builder.Append(Quote("is_lcd")).Append(":").Append(isLcd ? "true" : "false").Append(",");
            builder.Append(Quote("is_assembler")).Append(":").Append(isAssembler ? "true" : "false").Append(",");
            builder.Append(Quote("is_food_processor")).Append(":").Append(isFoodProcessor ? "true" : "false").Append(",");
            builder.Append(Quote("is_refinery")).Append(":").Append(isRefinery ? "true" : "false").Append(",");
            builder.Append(Quote("is_gas_generator")).Append(":").Append(isGasGenerator ? "true" : "false").Append(",");
            builder.Append(Quote("is_reactor")).Append(":").Append(isReactor ? "true" : "false").Append(",");
            builder.Append(Quote("is_gas_tank")).Append(":").Append(isGasTank ? "true" : "false").Append(",");
            builder.Append(Quote("is_connector")).Append(":").Append(isConnector ? "true" : "false").Append(",");
            builder.Append(Quote("is_cargo")).Append(":").Append(isCargo ? "true" : "false").Append(",");
            builder.Append(Quote("is_door")).Append(":").Append(isDoor ? "true" : "false").Append(",");
            builder.Append(Quote("is_hangar_door")).Append(":").Append(isHangarDoor ? "true" : "false").Append(",");
            builder.Append(Quote("is_light")).Append(":").Append(isLight ? "true" : "false").Append(",");
            builder.Append(Quote("is_sound")).Append(":").Append(isSound ? "true" : "false").Append(",");
            builder.Append(Quote("inventories")).Append(":").Append(SafeGridInventoriesJson(block, inventoryCount));
            builder.Append("}");
            return builder.ToString();
        }

        private string BuildGridBlockFallbackJson(object block)
        {
            if (block == null)
            {
                return "";
            }
            var name = ReadStringMember(block, "CustomName");
            var typeName = block.GetType().FullName ?? block.GetType().Name;
            var customData = ReadStringMember(block, "CustomData");
            var text = ReadSurfaceText(block);
            var typeKey = (typeName + " " + name + " " + customData).ToLowerInvariant();
            var isLcd = ContainsAny(typeKey, "textpanel", "textsurface", "lcd", "iim-main", "iim-inventory", "iim-warnings", "iim-actions", "iim-performance", "autocrafting");
            var isAssembler = ContainsAny(typeKey, "assembler");
            var isFoodProcessor = ContainsAny(typeKey, "foodprocessor", "food processor");
            var isRefinery = ContainsAny(typeKey, "refinery");
            var isGasGenerator = ContainsAny(typeKey, "oxygengenerator", "gasgenerator", "o2h2");
            var isReactor = ContainsAny(typeKey, "reactor");
            var isGasTank = ContainsAny(typeKey, "gastank", "oxygentank", "hydrogentank");
            var isConnector = ContainsAny(typeKey, "shipconnector", "connector");
            var isCargo = ContainsAny(typeKey, "cargo", "container");
            var isDoor = ContainsAny(typeKey, "door");
            var isHangarDoor = ContainsAny(typeKey, "hangardoor", "hangar door");
            var isLight = ContainsAny(typeKey, "lightingblock", "interiorlight", "reflectorlight", "light");
            var isSound = ContainsAny(typeKey, "soundblock", "sound block");
            if (!(isLcd || isAssembler || isFoodProcessor || isRefinery || isGasGenerator || isReactor || isGasTank || isConnector || isCargo || isDoor || isLight || isSound))
            {
                return "";
            }
            if (isLcd)
            {
                _lastGridSnapshotLcds++;
            }
            if (isAssembler || isFoodProcessor || isRefinery || isGasGenerator || isReactor || isGasTank)
            {
                _lastGridSnapshotMachines++;
            }
            return "{" +
                Quote("entity_id") + ":" + ReadLongMember(block, "EntityId", 0).ToString() + "," +
                Quote("name") + ":" + Quote(name) + "," +
                Quote("type") + ":" + Quote(typeName) + "," +
                Quote("subtype") + ":" + Quote("") + "," +
                Quote("same_construct") + ":true," +
                Quote("enabled") + ":" + (ReadBoolMember(block, "Enabled", true) ? "true" : "false") + "," +
                Quote("use_conveyor") + ":false," +
                Quote("inventory_count") + ":0," +
                Quote("surface_count") + ":" + (isLcd ? "1" : "0") + "," +
                Quote("text") + ":" + Quote(Limit(text, 600)) + "," +
                Quote("custom_data") + ":" + Quote(Limit(customData, 600)) + "," +
                Quote("assembler_mode") + ":" + Quote("") + "," +
                Quote("assembler_cooperative_mode") + ":false," +
                Quote("production_queue_count") + ":0," +
                Quote("production_queue") + ":[]," +
                Quote("gas_auto_refill") + ":false," +
                Quote("stockpile") + ":false," +
                Quote("gas_filled_ratio") + ":0," +
                Quote("door_open_ratio") + ":" + FormatDouble(ReadDoubleLikeMember(block, "OpenRatio")) + "," +
                Quote("door_status") + ":" + Quote(ReadStringMember(block, "Status")) + "," +
                Quote("color") + ":" + ReadColorJson(block) + "," +
                Quote("is_lcd") + ":" + (isLcd ? "true" : "false") + "," +
                Quote("is_assembler") + ":" + (isAssembler ? "true" : "false") + "," +
                Quote("is_food_processor") + ":" + (isFoodProcessor ? "true" : "false") + "," +
                Quote("is_refinery") + ":" + (isRefinery ? "true" : "false") + "," +
                Quote("is_gas_generator") + ":" + (isGasGenerator ? "true" : "false") + "," +
                Quote("is_reactor") + ":" + (isReactor ? "true" : "false") + "," +
                Quote("is_gas_tank") + ":" + (isGasTank ? "true" : "false") + "," +
                Quote("is_connector") + ":" + (isConnector ? "true" : "false") + "," +
                Quote("is_cargo") + ":" + (isCargo ? "true" : "false") + "," +
                Quote("is_door") + ":" + (isDoor ? "true" : "false") + "," +
                Quote("is_hangar_door") + ":" + (isHangarDoor ? "true" : "false") + "," +
                Quote("is_light") + ":" + (isLight ? "true" : "false") + "," +
                Quote("is_sound") + ":" + (isSound ? "true" : "false") + "," +
                Quote("inventories") + ":[]" +
                "}";
        }

        private string SafeGridInventoriesJson(object block, int inventoryCount)
        {
            try
            {
                return BuildGridInventoriesJson(block, inventoryCount);
            }
            catch (Exception ex)
            {
                RecordGridSnapshotSkip(block, ex);
                return "[]";
            }
        }

        private void RecordGridSnapshotSkip(object block, Exception ex)
        {
            _lastGridSnapshotSkippedBlocks++;
            if (_lastGridSnapshotSkipSamples.Length > 600)
            {
                return;
            }
            var sample = ReadStringMember(block, "CustomName");
            if (string.IsNullOrWhiteSpace(sample) && block != null)
            {
                sample = block.GetType().FullName ?? block.GetType().Name;
            }
            if (string.IsNullOrWhiteSpace(sample))
            {
                sample = "unknown";
            }
            if (_lastGridSnapshotSkipSamples.Length > 0)
            {
                _lastGridSnapshotSkipSamples += ";";
            }
            _lastGridSnapshotSkipSamples += Limit(sample, 80) + ":" + ex.GetType().Name;
        }

        private static string BuildGridInventoriesJson(object block, int inventoryCount)
        {
            var builder = new StringBuilder();
            builder.Append("[");
            var firstInventory = true;
            for (var index = 0; index < inventoryCount; index++)
            {
                var inventory = ReadInventory(block, index);
                if (inventory == null)
                {
                    continue;
                }
                if (!firstInventory)
                {
                    builder.Append(",");
                }
                firstInventory = false;
                builder.Append("{");
                builder.Append(Quote("index")).Append(":").Append(index.ToString()).Append(",");
                builder.Append(Quote("current_volume")).Append(":").Append(FormatDouble(ReadDoubleLikeMember(inventory, "CurrentVolume"))).Append(",");
                builder.Append(Quote("max_volume")).Append(":").Append(FormatDouble(ReadDoubleLikeMember(inventory, "MaxVolume"))).Append(",");
                builder.Append(Quote("is_full")).Append(":").Append(ReadBoolMember(inventory, "IsFull", false) ? "true" : "false").Append(",");
                builder.Append(Quote("items")).Append(":[");
                var firstItem = true;
                foreach (var item in ReadInventoryItems(inventory))
                {
                    var itemJson = BuildInventoryItemJson(item);
                    if (string.IsNullOrWhiteSpace(itemJson))
                    {
                        continue;
                    }
                    if (!firstItem)
                    {
                        builder.Append(",");
                    }
                    firstItem = false;
                    builder.Append(itemJson);
                }
                builder.Append("]}");
            }
            builder.Append("]");
            return builder.ToString();
        }

        private static string ReadSurfaceText(object block)
        {
            if (block == null)
            {
                return "";
            }
            string surfaceText;
            if (TryReadTextSurfaceText(block, out surfaceText))
            {
                return surfaceText;
            }
            var direct = FindInstanceMethod(block, "GetText", Type.EmptyTypes);
            if (direct != null)
            {
                try
                {
                    var value = direct.Invoke(block, null);
                    return value == null ? "" : value.ToString();
                }
                catch
                {
                }
            }
            return "";
        }

        private static bool TryReadTextSurfaceText(object block, out string text)
        {
            text = "";
            var surface = ReadTextSurface(block, 0);
            if (surface == null)
            {
                return false;
            }
            var method = FindInstanceMethod(surface, "GetText", Type.EmptyTypes);
            if (method == null)
            {
                return false;
            }
            try
            {
                var value = method.Invoke(surface, null);
                text = value == null ? "" : value.ToString();
                return true;
            }
            catch
            {
                text = "";
                return false;
            }
        }

        private static object ReadTextSurface(object block, int index)
        {
            var getSurface = FindInstanceMethod(block, "GetSurface", new[] { typeof(int) });
            if (getSurface == null)
            {
                return null;
            }
            try
            {
                return getSurface.Invoke(block, new object[] { index });
            }
            catch
            {
                return null;
            }
        }

        private string BuildInventoryJson(object inventory, int index, ref bool truncatedItems)
        {
            var builder = new StringBuilder();
            builder.Append("{");
            builder.Append(Quote("index")).Append(":").Append(index.ToString()).Append(",");
            builder.Append(Quote("current_volume")).Append(":").Append(FormatDouble(ReadDoubleLikeMember(inventory, "CurrentVolume"))).Append(",");
            builder.Append(Quote("max_volume")).Append(":").Append(FormatDouble(ReadDoubleLikeMember(inventory, "MaxVolume"))).Append(",");
            builder.Append(Quote("is_full")).Append(":").Append(ReadBoolMember(inventory, "IsFull", false) ? "true" : "false").Append(",");
            builder.Append(Quote("items")).Append(":[");
            var items = ReadInventoryItems(inventory);
            var firstItem = true;
            foreach (var item in items)
            {
                if (_lastInventorySnapshotItems >= InventorySnapshotItemCap)
                {
                    truncatedItems = true;
                    break;
                }
                var itemJson = BuildInventoryItemJson(item);
                if (string.IsNullOrWhiteSpace(itemJson))
                {
                    continue;
                }
                if (!firstItem)
                {
                    builder.Append(",");
                }
                firstItem = false;
                builder.Append(itemJson);
                _lastInventorySnapshotItems++;
            }
            builder.Append("]}");
            return builder.ToString();
        }

        private static string BuildInventoryItemJson(object item)
        {
            if (item == null)
            {
                return "";
            }
            var type = ReadObjectMember(item, "Type");
            var typeId = ReadStringMember(type, "TypeId");
            var subtypeId = ReadStringMember(type, "SubtypeId");
            if (string.IsNullOrWhiteSpace(typeId))
            {
                var content = ReadObjectMember(item, "Content");
                typeId = ReadStringMember(content, "TypeId");
                subtypeId = ReadStringMember(content, "SubtypeName");
                if (string.IsNullOrWhiteSpace(subtypeId))
                {
                    subtypeId = ReadStringMember(content, "SubtypeId");
                }
            }
            if (string.IsNullOrWhiteSpace(typeId))
            {
                typeId = ReadStringMember(type, "TypeIdString");
            }
            if (string.IsNullOrWhiteSpace(subtypeId))
            {
                subtypeId = ReadStringMember(type, "SubtypeName");
            }
            if (string.IsNullOrWhiteSpace(typeId))
            {
                typeId = type == null ? "" : type.ToString();
            }
            var amount = ReadDoubleLikeMember(item, "Amount");
            return "{" +
                Quote("type_id") + ":" + Quote(typeId) + "," +
                Quote("subtype_id") + ":" + Quote(subtypeId) + "," +
                Quote("amount") + ":" + FormatDouble(amount) +
                "}";
        }

        private static string BuildProductionQueueJson(object block)
        {
            var builder = new StringBuilder();
            builder.Append("[");
            var firstItem = true;
            var count = 0;
            foreach (var item in ReadProductionQueueItems(block))
            {
                if (count >= ProductionQueueItemCap)
                {
                    break;
                }
                var itemJson = BuildProductionQueueItemJson(item);
                if (string.IsNullOrWhiteSpace(itemJson))
                {
                    continue;
                }
                if (!firstItem)
                {
                    builder.Append(",");
                }
                firstItem = false;
                builder.Append(itemJson);
                count++;
            }
            builder.Append("]");
            return builder.ToString();
        }

        private static string BuildProductionQueueItemJson(object item)
        {
            if (item == null)
            {
                return "";
            }
            var blueprint = ReadObjectMember(item, "BlueprintId");
            var blueprintId = blueprint == null ? "" : blueprint.ToString();
            if (string.IsNullOrWhiteSpace(blueprintId))
            {
                blueprintId = ReadStringMember(item, "BlueprintId");
            }
            if (string.IsNullOrWhiteSpace(blueprintId))
            {
                blueprintId = ReadStringMember(item, "Blueprint");
            }
            return "{" +
                Quote("item_id") + ":" + ReadLongMember(item, "ItemId", 0).ToString() + "," +
                Quote("blueprint_id") + ":" + Quote(blueprintId) + "," +
                Quote("amount") + ":" + FormatDouble(ReadDoubleLikeMember(item, "Amount")) +
                "}";
        }

        private static IEnumerable<object> ReadProductionQueueItems(object block)
        {
            var empty = new List<object>();
            if (block == null)
            {
                return empty;
            }
            foreach (var method in block.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            {
                if (!string.Equals(method.Name, "GetQueue", StringComparison.Ordinal) &&
                    !method.Name.EndsWith(".GetQueue", StringComparison.Ordinal))
                {
                    continue;
                }
                var parameters = method.GetParameters();
                if (parameters.Length != 1 || !parameters[0].ParameterType.IsGenericType)
                {
                    continue;
                }
                try
                {
                    var list = Activator.CreateInstance(parameters[0].ParameterType);
                    method.Invoke(block, new[] { list });
                    var result = new List<object>();
                    foreach (var item in (System.Collections.IEnumerable)list)
                    {
                        result.Add(item);
                    }
                    return result;
                }
                catch
                {
                }
            }
            return empty;
        }

        private static bool ReadGasAutoRefill(object block)
        {
            return ReadBoolMember(block, "AutoRefill", ReadBoolMember(block, "AutoRefillBottles", false));
        }

        private bool StageRequestIfNew(string bridgeId, int sequence, string body)
        {
            int last;
            if (_lastSequences.TryGetValue(bridgeId, out last) && last >= sequence)
            {
                return false;
            }
            var path = Path.Combine(_root, "data", "bridge_requests", SafeFileName(bridgeId) + ".json");
            File.WriteAllText(path, body, Utf8NoBom);
            _lastSequences[bridgeId] = sequence;
            return true;
        }

        private bool ReturnResultIfPresent(object programmableBlock, string customData, string bridgeId, int sequence)
        {
            var path = Path.Combine(_root, "data", "bridge_results", SafeFileName(bridgeId) + ".json");
            if (!File.Exists(path))
            {
                _lastResultState = "result_file_missing";
                return false;
            }
            var result = File.ReadAllText(path, Encoding.UTF8);
            if (!string.Equals(ExtractJsonString(result, "message_kind"), "result", StringComparison.OrdinalIgnoreCase))
            {
                _lastResultState = "result_kind_mismatch";
                return false;
            }
            if (ExtractJsonInt(result, "sequence") != sequence)
            {
                _lastResultState = "result_sequence_mismatch";
                return false;
            }
            if (!string.Equals(ExtractJsonString(result, "bridge_id"), bridgeId, StringComparison.OrdinalIgnoreCase))
            {
                _lastResultState = "result_bridge_mismatch";
                return false;
            }
            var wrapped = Begin + "\n" + result + "\n" + End;
            var panelName = ExtractConfigValue(customData, "text_panel_name");
            if (!string.IsNullOrWhiteSpace(panelName))
            {
                WriteTextPanel(panelName, wrapped);
            }
            WriteStringMember(programmableBlock, "CustomData", ReplaceMarkedBlock(customData, wrapped));
            _lastResultState = "returned";
            return true;
        }

        private void WriteTextPanel(string panelName, string text)
        {
            if (MyAPIGateway.Entities == null)
            {
                return;
            }
            var entities = new HashSet<IMyEntity>();
            MyAPIGateway.Entities.GetEntities(entities);
            foreach (var entity in entities)
            {
                if (entity == null)
                {
                    continue;
                }
                var grid = entity as IMyCubeGrid;
                if (grid != null)
                {
                    if (WriteTextPanelOnGrid(grid, panelName, text))
                    {
                        return;
                    }
                    continue;
                }
                if (TryWriteTextPanelEntity(entity, panelName, text))
                {
                    return;
                }
            }
        }

        private bool WriteTextPanelOnGrid(IMyCubeGrid grid, string panelName, string text)
        {
            var blocks = new List<IMySlimBlock>();
            try
            {
                grid.GetBlocks(blocks, block => block != null && block.FatBlock != null);
            }
            catch
            {
                return false;
            }
            foreach (var block in blocks)
            {
                if (block != null && block.FatBlock != null && TryWriteTextPanelEntity(block.FatBlock, panelName, text))
                {
                    return true;
                }
            }
            return false;
        }

        private static bool TryWriteTextPanelEntity(object entity, string panelName, string text)
        {
            if (entity == null || !string.Equals(ReadStringMember(entity, "CustomName"), panelName, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            var typeName = entity.GetType().FullName ?? entity.GetType().Name;
            if (typeName.IndexOf("TextPanel", StringComparison.OrdinalIgnoreCase) < 0 && typeName.IndexOf("TextSurface", StringComparison.OrdinalIgnoreCase) < 0)
            {
                return false;
            }
            if (TryWriteTextSurface(entity, text))
            {
                return true;
            }
            var surface = ReadTextSurface(entity, 0);
            return surface != null && TryWriteTextSurface(surface, text);
        }

        private static bool TryWriteTextSurface(object target, string text)
        {
            var method = FindInstanceMethod(target, "WriteText", new[] { typeof(string), typeof(bool) });
            if (method == null)
            {
                return false;
            }
            try
            {
                method.Invoke(target, new object[] { text, false });
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static string ResolveRoot()
        {
            var env = Environment.GetEnvironmentVariable("NOVALI_CLIENT_SIDE_PB_ROOT");
            if (!string.IsNullOrWhiteSpace(env))
            {
                return Path.GetFullPath(env);
            }
            var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(profile, "Documents", "VScode", ".venv", "ClientSide_PB_Script");
        }

        private void WriteStatus(string state)
        {
            _lastStatus = state;
            try
            {
                Directory.CreateDirectory(Path.Combine(_root, "data"));
                var text = "{" +
                    Quote("schema") + ":" + Quote("novali.client_side_pb.plugin_status.v1") + "," +
                    Quote("state") + ":" + Quote(_lastStatus) + "," +
                    Quote("updated_at") + ":" + Quote(DateTime.UtcNow.ToString("o")) + "," +
                    Quote("root") + ":" + Quote(_root ?? "") + "," +
                    Quote("entity_count") + ":" + _lastEntityCount.ToString() + "," +
                    Quote("programmable_block_candidates") + ":" + _lastProgrammableBlockCandidates.ToString() + "," +
                    Quote("marked_mailboxes") + ":" + _lastMarkedMailboxes.ToString() + "," +
                    Quote("staged_requests") + ":" + _stagedRequests.ToString() + "," +
                    Quote("returned_results") + ":" + _returnedResults.ToString() + "," +
                    Quote("last_bridge_id") + ":" + Quote(_lastBridgeId) + "," +
                    Quote("last_sequence") + ":" + _lastSequence.ToString() + "," +
                    Quote("last_mailbox_kind") + ":" + Quote(_lastMailboxKind) + "," +
                    Quote("last_result_state") + ":" + Quote(_lastResultState) + "," +
                    Quote("last_inventory_snapshot_state") + ":" + Quote(_lastInventorySnapshotState) + "," +
                    Quote("last_inventory_snapshot_blocks") + ":" + _lastInventorySnapshotBlocks.ToString() + "," +
                    Quote("last_inventory_snapshot_items") + ":" + _lastInventorySnapshotItems.ToString() + "," +
                    Quote("last_inventory_snapshot_skipped_blocks") + ":" + _lastInventorySnapshotSkippedBlocks.ToString() + "," +
                    Quote("last_grid_snapshot_state") + ":" + Quote(_lastGridSnapshotState) + "," +
                    Quote("last_grid_snapshot_blocks") + ":" + _lastGridSnapshotBlocks.ToString() + "," +
                    Quote("last_grid_snapshot_lcds") + ":" + _lastGridSnapshotLcds.ToString() + "," +
                    Quote("last_grid_snapshot_machines") + ":" + _lastGridSnapshotMachines.ToString() + "," +
                    Quote("last_grid_snapshot_skipped_blocks") + ":" + _lastGridSnapshotSkippedBlocks.ToString() + "," +
                    Quote("last_grid_snapshot_truncated_blocks") + ":" + (_lastGridSnapshotTruncatedBlocks ? "true" : "false") + "," +
                    Quote("last_grid_snapshot_skip_samples") + ":" + Quote(_lastGridSnapshotSkipSamples) + "," +
                    Quote("visible_grid_scan_state") + ":" + Quote(_lastVisibleGridScanState) + "," +
                    Quote("visible_grid_scan_blocks") + ":" + _lastVisibleGridScanBlocks.ToString() + "," +
                    Quote("visible_grid_scan_machines") + ":" + _lastVisibleGridScanMachines.ToString() + "," +
                    Quote("visible_grid_scan_assemblers") + ":" + _lastVisibleGridScanAssemblers.ToString() + "," +
                    Quote("visible_grid_scan_active_assemblers") + ":" + _lastVisibleGridScanActiveAssemblers.ToString() + "," +
                    Quote("visible_grid_scan_food_processors") + ":" + _lastVisibleGridScanFoodProcessors.ToString() + "," +
                    Quote("visible_grid_scan_refineries") + ":" + _lastVisibleGridScanRefineries.ToString() + "," +
                    Quote("visible_grid_scan_active_refineries") + ":" + _lastVisibleGridScanActiveRefineries.ToString() + "," +
                    Quote("visible_grid_scan_production_summary") + ":" + Quote(_lastVisibleGridScanProductionSummary) +
                    "}";
                File.WriteAllText(Path.Combine(_root, "data", "plugin_status.json"), text, Utf8NoBom);
            }
            catch
            {
            }
        }

        private static string ExtractMarkedBody(string text)
        {
            var start = text.IndexOf(Begin, StringComparison.OrdinalIgnoreCase);
            var end = text.IndexOf(End, StringComparison.OrdinalIgnoreCase);
            if (start < 0 || end <= start)
            {
                return "";
            }
            start += Begin.Length;
            return text.Substring(start, end - start).Trim();
        }

        private static string ReplaceMarkedBlock(string original, string replacement)
        {
            var start = original.IndexOf(Begin, StringComparison.OrdinalIgnoreCase);
            var end = original.IndexOf(End, StringComparison.OrdinalIgnoreCase);
            if (start < 0 || end <= start)
            {
                return original.TrimEnd() + "\n\n" + replacement + "\n";
            }
            end += End.Length;
            return original.Substring(0, start) + replacement + original.Substring(end);
        }

        private static string ExtractConfigValue(string text, string key)
        {
            foreach (var raw in text.Split('\n'))
            {
                var line = raw.Trim();
                var split = line.IndexOf('=');
                if (split <= 0)
                {
                    continue;
                }
                if (string.Equals(line.Substring(0, split).Trim(), key, StringComparison.OrdinalIgnoreCase))
                {
                    return line.Substring(split + 1).Trim();
                }
            }
            return "";
        }

        private static string ExtractJsonString(string json, string key)
        {
            var needle = "\"" + key + "\"";
            var start = json.IndexOf(needle, StringComparison.OrdinalIgnoreCase);
            if (start < 0)
            {
                return "";
            }
            start += needle.Length;
            while (start < json.Length && char.IsWhiteSpace(json[start]))
            {
                start++;
            }
            if (start >= json.Length || json[start] != ':')
            {
                return "";
            }
            start++;
            while (start < json.Length && char.IsWhiteSpace(json[start]))
            {
                start++;
            }
            if (start >= json.Length || json[start] != '"')
            {
                return "";
            }
            start++;
            var end = json.IndexOf("\"", start, StringComparison.OrdinalIgnoreCase);
            return end > start ? json.Substring(start, end - start) : "";
        }

        private static int ExtractJsonInt(string json, string key)
        {
            var needle = "\"" + key + "\"";
            var start = json.IndexOf(needle, StringComparison.OrdinalIgnoreCase);
            if (start < 0)
            {
                return -1;
            }
            start += needle.Length;
            while (start < json.Length && char.IsWhiteSpace(json[start]))
            {
                start++;
            }
            if (start >= json.Length || json[start] != ':')
            {
                return -1;
            }
            start++;
            while (start < json.Length && char.IsWhiteSpace(json[start]))
            {
                start++;
            }
            var end = start;
            while (end < json.Length && char.IsDigit(json[end]))
            {
                end++;
            }
            int value;
            return int.TryParse(json.Substring(start, end - start), out value) ? value : -1;
        }

        private static MethodInfo FindInstanceMethod(object source, string name, Type[] parameterTypes)
        {
            if (source == null)
            {
                return null;
            }
            var methods = source.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            foreach (var method in methods)
            {
                if (!string.Equals(method.Name, name, StringComparison.Ordinal) &&
                    !method.Name.EndsWith("." + name, StringComparison.Ordinal))
                {
                    continue;
                }
                var parameters = method.GetParameters();
                if (parameters.Length != parameterTypes.Length)
                {
                    continue;
                }
                var matches = true;
                for (var index = 0; index < parameters.Length; index++)
                {
                    if (parameters[index].ParameterType != parameterTypes[index])
                    {
                        matches = false;
                        break;
                    }
                }
                if (matches)
                {
                    return method;
                }
            }
            return null;
        }

        private static string SafeFileName(string value)
        {
            var builder = new StringBuilder();
            foreach (var c in value)
            {
                builder.Append(char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_');
            }
            return builder.Length == 0 ? "bridge" : builder.ToString();
        }

        private static string ReadStringMember(object source, string name)
        {
            if (source == null)
            {
                return "";
            }
            var type = source.GetType();
            PropertyInfo property = null;
            try
            {
                property = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            }
            catch
            {
            }
            if (property != null)
            {
                try
                {
                    var value = property.GetValue(source, null);
                    return value == null ? "" : value.ToString();
                }
                catch
                {
                }
            }
            var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (field != null)
            {
                try
                {
                    var value = field.GetValue(source);
                    return value == null ? "" : value.ToString();
                }
                catch
                {
                }
            }
            return "";
        }

        private static object ReadObjectMember(object source, string name)
        {
            if (source == null)
            {
                return null;
            }
            var type = source.GetType();
            PropertyInfo property = null;
            try
            {
                property = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            }
            catch
            {
            }
            if (property != null)
            {
                try
                {
                    return property.GetValue(source, null);
                }
                catch
                {
                }
            }
            var field = type.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (field == null)
            {
                return null;
            }
            try
            {
                return field.GetValue(source);
            }
            catch
            {
                return null;
            }
        }

        private static int ReadIntMember(object source, string name, int fallback)
        {
            var value = ReadObjectMember(source, name);
            if (value == null)
            {
                return fallback;
            }
            try
            {
                return Convert.ToInt32(value, CultureInfo.InvariantCulture);
            }
            catch
            {
                return fallback;
            }
        }

        private static long ReadLongMember(object source, string name, long fallback)
        {
            var value = ReadObjectMember(source, name);
            if (value == null)
            {
                return fallback;
            }
            try
            {
                return Convert.ToInt64(value, CultureInfo.InvariantCulture);
            }
            catch
            {
                return fallback;
            }
        }

        private static bool ReadBoolMember(object source, string name, bool fallback)
        {
            var value = ReadObjectMember(source, name);
            if (value == null)
            {
                return fallback;
            }
            if (value is bool)
            {
                return (bool)value;
            }
            bool parsed;
            return bool.TryParse(value.ToString(), out parsed) ? parsed : fallback;
        }

        private static double ReadDoubleLikeMember(object source, string name)
        {
            var value = ReadObjectMember(source, name);
            if (value == null)
            {
                return 0.0;
            }
            var typeName = value.GetType().FullName ?? value.GetType().Name;
            if (typeName.IndexOf("MyFixedPoint", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                var fixedPoint = ReadFixedPoint(value);
                if (!double.IsNaN(fixedPoint))
                {
                    return fixedPoint;
                }
            }
            if (value is IConvertible)
            {
                try
                {
                    return Convert.ToDouble(value, CultureInfo.InvariantCulture);
                }
                catch
                {
                }
            }
            var fallbackFixedPoint = ReadFixedPoint(value);
            if (!double.IsNaN(fallbackFixedPoint))
            {
                return fallbackFixedPoint;
            }
            return ParseLeadingDouble(value.ToString());
        }

        private static string ReadColorJson(object source)
        {
            var color = ReadObjectMember(source, "Color");
            if (color == null)
            {
                return "{\"r\":0,\"g\":0,\"b\":0,\"a\":255}";
            }
            return "{" +
                Quote("r") + ":" + ReadIntMember(color, "R", 0).ToString() + "," +
                Quote("g") + ":" + ReadIntMember(color, "G", 0).ToString() + "," +
                Quote("b") + ":" + ReadIntMember(color, "B", 0).ToString() + "," +
                Quote("a") + ":" + ReadIntMember(color, "A", 255).ToString() +
                "}";
        }

        private static double ReadFixedPoint(object value)
        {
            var rawValue = ReadObjectMember(value, "RawValue");
            if (rawValue == null)
            {
                return double.NaN;
            }
            try
            {
                var raw = Convert.ToDouble(rawValue, CultureInfo.InvariantCulture);
                var divider = 1000000.0;
                var dividerField = value.GetType().GetField("Divider", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
                if (dividerField != null)
                {
                    divider = Convert.ToDouble(dividerField.GetValue(null), CultureInfo.InvariantCulture);
                }
                return divider > 0 ? raw / divider : double.NaN;
            }
            catch
            {
                return double.NaN;
            }
        }

        private static object ReadInventory(object block, int index)
        {
            if (block == null)
            {
                return null;
            }
            var methods = block.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            foreach (var method in methods)
            {
                if (method.Name.IndexOf("GetInventory", StringComparison.OrdinalIgnoreCase) < 0 || method.GetParameters().Length != 1)
                {
                    continue;
                }
                try
                {
                    return method.Invoke(block, new object[] { index });
                }
                catch
                {
                    return null;
                }
            }
            foreach (var method in methods)
            {
                if (method.Name.IndexOf("GetInventory", StringComparison.OrdinalIgnoreCase) < 0 || method.GetParameters().Length != 0)
                {
                    continue;
                }
                try
                {
                    return method.Invoke(block, null);
                }
                catch
                {
                    return null;
                }
            }
            return null;
        }

        private static IEnumerable<object> ReadInventoryItems(object inventory)
        {
            var empty = new List<object>();
            if (inventory == null)
            {
                return empty;
            }
            foreach (var method in inventory.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            {
                if (!string.Equals(method.Name, "GetItems", StringComparison.Ordinal))
                {
                    continue;
                }
                var parameters = method.GetParameters();
                if (parameters.Length == 0)
                {
                    try
                    {
                        var value = method.Invoke(inventory, null);
                        var enumerable = value as System.Collections.IEnumerable;
                        if (enumerable == null)
                        {
                            continue;
                        }
                        var result = new List<object>();
                        foreach (var item in enumerable)
                        {
                            result.Add(item);
                        }
                        return result;
                    }
                    catch
                    {
                    }
                }
                if (parameters.Length < 1 || parameters.Length > 2)
                {
                    continue;
                }
                var listType = parameters[0].ParameterType;
                if (!listType.IsGenericType)
                {
                    continue;
                }
                try
                {
                    var list = Activator.CreateInstance(listType);
                    method.Invoke(inventory, parameters.Length == 1 ? new[] { list } : new[] { list, null });
                    var result = new List<object>();
                    foreach (var item in (System.Collections.IEnumerable)list)
                    {
                        result.Add(item);
                    }
                    return result;
                }
                catch
                {
                }
            }
            return empty;
        }

        private static string BlockTypeName(object block)
        {
            var definition = ReadObjectMember(block, "BlockDefinition");
            var typeId = ReadStringMember(definition, "TypeIdString");
            return string.IsNullOrWhiteSpace(typeId) ? block.GetType().Name : typeId;
        }

        private static string BlockSubtypeName(object block)
        {
            var definition = ReadObjectMember(block, "BlockDefinition");
            var subtype = ReadStringMember(definition, "SubtypeId");
            if (!string.IsNullOrWhiteSpace(subtype))
            {
                return subtype;
            }
            subtype = ReadStringMember(definition, "SubtypeName");
            return subtype;
        }

        private static double ParseLeadingDouble(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return 0.0;
            }
            var builder = new StringBuilder();
            foreach (var c in text.Trim())
            {
                if (char.IsDigit(c) || c == '.' || c == '-' || c == '+')
                {
                    builder.Append(c);
                    continue;
                }
                if (builder.Length > 0)
                {
                    break;
                }
            }
            double parsed;
            return double.TryParse(builder.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out parsed) ? parsed : 0.0;
        }

        private static string FormatDouble(double value)
        {
            return value.ToString("0.######", CultureInfo.InvariantCulture);
        }

        private static bool ContainsAny(string text, params string[] needles)
        {
            foreach (var needle in needles)
            {
                if (text.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }
            return false;
        }

        private static string Limit(string value, int maxLength)
        {
            if (string.IsNullOrEmpty(value) || value.Length <= maxLength)
            {
                return value ?? "";
            }
            return value.Substring(0, Math.Max(0, maxLength));
        }

        private static void WriteStringMember(object source, string name, string value)
        {
            if (source == null)
            {
                return;
            }
            var property = source.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (property != null && property.CanWrite)
            {
                property.SetValue(source, value, null);
            }
        }

        private static string Quote(string value)
        {
            var builder = new StringBuilder();
            builder.Append("\"");
            foreach (var c in value ?? "")
            {
                if (c == '\\')
                {
                    builder.Append("\\\\");
                }
                else if (c == '"')
                {
                    builder.Append("\\\"");
                }
                else if (c == '\n')
                {
                    builder.Append("\\n");
                }
                else if (c == '\r')
                {
                    builder.Append("\\r");
                }
                else if (c == '\t')
                {
                    builder.Append("\\t");
                }
                else if (c == '\b')
                {
                    builder.Append("\\b");
                }
                else if (c == '\f')
                {
                    builder.Append("\\f");
                }
                else if (char.IsControl(c))
                {
                    builder.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                }
                else
                {
                    builder.Append(c);
                }
            }
            builder.Append("\"");
            return builder.ToString();
        }
    }
}
