param(
    [string]$TaskName = "JobBot Backup"
)

$ErrorActionPreference = "Stop"

if ($PSScriptRoot) {
    $scriptDir = $PSScriptRoot
}
elseif ($PSCommandPath) {
    $scriptDir = Split-Path -Parent $PSCommandPath
}
else {
    $scriptDir = (Get-Location).Path
}

$backupScript = Join-Path $scriptDir "backup_jobbot.ps1"
if (-not (Test-Path $backupScript)) {
    throw "Could not find backup_jobbot.ps1 at $backupScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backupScript`""

$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 2 -At 12:00AM
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Scheduled task created: $TaskName"
