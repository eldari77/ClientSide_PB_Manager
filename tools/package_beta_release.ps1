param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Version = ("beta-" + (Get-Date -Format "yyyyMMdd-HHmm")),
    [string]$OutputRoot = "",
    [string]$Configuration = "Release",
    [switch]$SkipBuild,
    [switch]$SelfContainedManager,
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot "artifacts\beta_handoff"
}

$packageName = "NOVALI-ClientSidePB-Bridge-$Version"
$stageRoot = Join-Path $OutputRoot $packageName
$zipPath = Join-Path $OutputRoot "$packageName.zip"
$buildRoot = Join-Path $ProjectRoot "artifacts\beta_build"
$managerPublishDir = Join-Path $buildRoot "manager"
$pluginDll = Join-Path $ProjectRoot "artifacts\plugin_handoff\NOVALI.ClientSidePBBridge.dll"

function Ensure-Directory([string]$Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-RequiredFile([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required package source file not found: $Source"
    }
    Ensure-Directory ([System.IO.Path]::GetDirectoryName($Destination))
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Copy-RequiredDirectory([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required package source directory not found: $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    Ensure-Directory ([System.IO.Path]::GetDirectoryName($Destination))
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

if (-not $SkipBuild) {
    Ensure-Directory $managerPublishDir
    $managerProject = Join-Path $ProjectRoot "manager\NOVALI.ClientSidePBManager.csproj"
    $publishArgs = @("publish", $managerProject, "--nologo", "-c", $Configuration, "-o", $managerPublishDir)
    if ($SelfContainedManager) {
        $publishArgs += @("-r", "win-x64", "--self-contained", "true")
    }
    else {
        $publishArgs += @("--self-contained", "false")
    }
    & dotnet @publishArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Manager publish failed with exit code $LASTEXITCODE"
    }

    & (Join-Path $ProjectRoot "tools\build_local_plugin.ps1") -ProjectRoot $ProjectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Plugin build failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $managerPublishDir "NOVALI.ClientSidePBManager.exe"))) {
    throw "Manager executable was not found after publish: manager\NOVALI.ClientSidePBManager.exe"
}
if (-not (Test-Path -LiteralPath $pluginDll)) {
    throw "Plugin DLL was not found after build: plugin\NOVALI.ClientSidePBBridge.dll"
}

Ensure-Directory $OutputRoot
if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
Ensure-Directory $stageRoot

Copy-RequiredFile (Join-Path $ProjectRoot "docs\beta_handoff\README-START-HERE.md") (Join-Path $stageRoot "README-START-HERE.md")
Copy-RequiredFile (Join-Path $ProjectRoot "LICENSE.md") (Join-Path $stageRoot "LICENSE.md")
Copy-RequiredFile (Join-Path $ProjectRoot "docs\beta_handoff\setup-guide.md") (Join-Path $stageRoot "docs\setup-guide.md")
Copy-RequiredFile (Join-Path $ProjectRoot "docs\beta_handoff\safety-and-server-notes.md") (Join-Path $stageRoot "docs\safety-and-server-notes.md")
Copy-RequiredFile (Join-Path $ProjectRoot "docs\beta_handoff\profiling-checklist.md") (Join-Path $stageRoot "docs\profiling-checklist.md")

$scriptMappings = @(
    @{ Source = "packaging\scripts\install-or-update.ps1"; Destination = "scripts\install-or-update.ps1" },
    @{ Source = "packaging\scripts\open-manager.ps1"; Destination = "scripts\open-manager.ps1" },
    @{ Source = "packaging\scripts\start-worker.ps1"; Destination = "scripts\start-worker.ps1" },
    @{ Source = "packaging\scripts\stop-worker.ps1"; Destination = "scripts\stop-worker.ps1" }
)
foreach ($mapping in $scriptMappings) {
    Copy-RequiredFile (Join-Path $ProjectRoot $mapping.Source) (Join-Path $stageRoot $mapping.Destination)
}

Copy-RequiredFile (Join-Path $ProjectRoot "pb_shim\ClientSidePBBridgeShim.cs") (Join-Path $stageRoot "pb\ClientSidePBBridgeShim.cs")
Copy-RequiredFile (Join-Path $ProjectRoot "packaging\pb\sample-customdata.txt") (Join-Path $stageRoot "pb\sample-customdata.txt")
Copy-RequiredFile $pluginDll (Join-Path $stageRoot "plugin\NOVALI.ClientSidePBBridge.dll")
Copy-RequiredDirectory $managerPublishDir (Join-Path $stageRoot "manager")

Copy-RequiredFile (Join-Path $ProjectRoot "docker-compose.yml") (Join-Path $stageRoot "docker-compose.yml")
Copy-RequiredFile (Join-Path $ProjectRoot "Dockerfile") (Join-Path $stageRoot "Dockerfile")
Copy-RequiredFile (Join-Path $ProjectRoot "requirements.txt") (Join-Path $stageRoot "requirements.txt")
Copy-RequiredFile (Join-Path $ProjectRoot "README.md") (Join-Path $stageRoot "docs\project-readme.md")

foreach ($directory in @("worker", "workshop", "bridge", "discovery", "virtual_pb_runner", "client_plugins")) {
    Copy-RequiredDirectory (Join-Path $ProjectRoot $directory) (Join-Path $stageRoot $directory)
}

Ensure-Directory (Join-Path $stageRoot "data")
foreach ($dataFile in @("bridge_limits.json", "profile_pack.json", "bridges.json", "bridge_scripts.json", "script_instances.json", "virtual_pb_capabilities.json")) {
    $source = Join-Path $ProjectRoot "data\$dataFile"
    if (Test-Path -LiteralPath $source) {
        Copy-RequiredFile $source (Join-Path $stageRoot "data\$dataFile")
    }
}
$workerConfigSource = Join-Path $ProjectRoot "data\worker_configs"
if (Test-Path -LiteralPath $workerConfigSource) {
    Copy-RequiredDirectory $workerConfigSource (Join-Path $stageRoot "data\worker_configs")
}

$manifest = [ordered]@{
    schema = "novali.client_side_pb.beta_handoff.v1"
    version = $Version
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    layout = @(
        "README-START-HERE.md",
        "LICENSE.md",
        "docs\setup-guide.md",
        "docs\safety-and-server-notes.md",
        "docs\profiling-checklist.md",
        "scripts\install-or-update.ps1",
        "manager\NOVALI.ClientSidePBManager.exe",
        "plugin\NOVALI.ClientSidePBBridge.dll",
        "pb\ClientSidePBBridgeShim.cs",
        "pb\sample-customdata.txt",
        "docker-compose.yml"
    )
}
Set-Content -LiteralPath (Join-Path $stageRoot "release-manifest.json") -Value ($manifest | ConvertTo-Json -Depth 4) -Encoding UTF8

Get-ChildItem -LiteralPath $stageRoot -Directory -Filter "__pycache__" -Recurse | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $stageRoot -File -Filter "*.pyc" -Recurse | Remove-Item -Force

if (-not $NoZip) {
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -LiteralPath $stageRoot -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host "Created beta handoff ZIP: $zipPath"
}

Write-Host "Created beta handoff folder: $stageRoot"
return $stageRoot
