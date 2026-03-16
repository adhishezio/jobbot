param(
    [string]$BackupRoot = "F:\jobbot_backup"
)

$ErrorActionPreference = "Stop"

function Get-ProjectRoot {
    if ($PSScriptRoot) {
        $scriptDir = $PSScriptRoot
    }
    elseif ($PSCommandPath) {
        $scriptDir = Split-Path -Parent $PSCommandPath
    }
    else {
        $scriptDir = (Get-Location).Path
    }

    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Read-DotEnv {
    param([string]$EnvPath)

    $values = @{}
    if (-not (Test-Path $EnvPath)) {
        return $values
    }

    foreach ($line in Get-Content $EnvPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }

        $parts = $trimmed.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"')
        $values[$key] = $value
    }

    return $values
}

$projectRoot = Get-ProjectRoot
$envValues = Read-DotEnv -EnvPath (Join-Path $projectRoot ".env")

$pgUser = $envValues["POSTGRES_USER"]
if (-not $pgUser) {
    $pgUser = "postgres"
}

$pgDatabase = $envValues["POSTGRES_DB"]
if (-not $pgDatabase) {
    $pgDatabase = "jobbot_db"
}

if (-not (Test-Path $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
}

$timestamp = (Get-Date).ToString("o")
$snapshotRoot = Join-Path $BackupRoot "current"
$tempRoot = Join-Path $BackupRoot "_current_tmp"
$dbDir = Join-Path $tempRoot "database"
$filesDir = Join-Path $tempRoot "files"
$metaDir = Join-Path $tempRoot "meta"
$statusPath = Join-Path $projectRoot "files\backup_status.json"

if (Test-Path $tempRoot) {
    Remove-Item -Path $tempRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $dbDir -Force | Out-Null
New-Item -ItemType Directory -Path $filesDir -Force | Out-Null
New-Item -ItemType Directory -Path $metaDir -Force | Out-Null

$dumpPath = Join-Path $dbDir "jobbot.sql"
$dumpErrorPath = Join-Path $dbDir "pg_dump.stderr.log"

$dumpProcess = Start-Process `
    -FilePath "docker" `
    -ArgumentList @(
        "exec",
        "jobbot_postgres",
        "pg_dump",
        "-U", $pgUser,
        "-d", $pgDatabase,
        "--no-owner",
        "--no-privileges"
    ) `
    -NoNewWindow `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $dumpPath `
    -RedirectStandardError $dumpErrorPath

if ($dumpProcess.ExitCode -ne 0) {
    throw "pg_dump failed. Check $dumpErrorPath"
}

$projectFiles = Join-Path $projectRoot "files"
if (Test-Path $projectFiles) {
    Copy-Item -Path (Join-Path $projectFiles "*") -Destination $filesDir -Recurse -Force
}

$projectSecrets = Join-Path $projectRoot "secrets"
if (Test-Path $projectSecrets) {
    Copy-Item -Path $projectSecrets -Destination $tempRoot -Recurse -Force
}

$projectEnv = Join-Path $projectRoot ".env"
if (Test-Path $projectEnv) {
    Copy-Item -Path $projectEnv -Destination $metaDir -Force
}

$workflowDir = Join-Path $projectRoot "n8n"
if (Test-Path $workflowDir) {
    Copy-Item -Path $workflowDir -Destination $tempRoot -Recurse -Force
}

$manifest = @{
    created_at = $timestamp
    project_root = $projectRoot
    backup_root = $BackupRoot
    snapshot_root = $snapshotRoot
    postgres_user = $pgUser
    postgres_database = $pgDatabase
    included = @(
        "database SQL dump",
        "files directory",
        "secrets directory",
        ".env",
        "n8n workflow exports"
    )
}

$manifestJson = $manifest | ConvertTo-Json -Depth 4
$manifestJson | Set-Content -Path (Join-Path $metaDir "backup_manifest.json") -Encoding UTF8

if (Test-Path $snapshotRoot) {
    Remove-Item -Path $snapshotRoot -Recurse -Force
}
Move-Item -Path $tempRoot -Destination $snapshotRoot

if (-not (Test-Path (Split-Path -Parent $statusPath))) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $statusPath) -Force | Out-Null
}
$manifestJson | Set-Content -Path $statusPath -Encoding UTF8

Write-Host "Backup completed successfully."
Write-Host "Snapshot location: $snapshotRoot"
