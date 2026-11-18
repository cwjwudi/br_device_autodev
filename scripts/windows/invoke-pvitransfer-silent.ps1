param(
    [Parameter(Mandatory = $true)]
    [string]$PilPath,

    [string]$LogPath,

    [string]$PviTransferPath = "D:\BRAutomation\AS65\PVI6\PVI\Tools\PVITransfer\PVITransfer.exe",

    [string]$Conn,

    [int]$MaxWaitSeconds = 150,

    [int]$SuccessExitGraceSeconds = 3,

    [long]$DeadlineTicks = 0
)

$ErrorActionPreference = "Stop"
$frequency = [System.Diagnostics.Stopwatch]::Frequency
$deadline = [System.Diagnostics.Stopwatch]::GetTimestamp() + $MaxWaitSeconds * $frequency
if ($DeadlineTicks) { $deadline = [Math]::Min($deadline, $DeadlineTicks) }

$resolvedPvi = (Resolve-Path -LiteralPath $PviTransferPath).Path
$resolvedPil = (Resolve-Path -LiteralPath $PilPath).Path

if (-not $LogPath) {
    $LogPath = [System.IO.Path]::ChangeExtension($resolvedPil, ".log")
}

$resolvedLog = [System.IO.Path]::GetFullPath($LogPath)
$workDir = Split-Path -Parent $resolvedPil

Remove-Item -LiteralPath $resolvedLog -ErrorAction SilentlyContinue

function Read-LogLines {
    param([Parameter(Mandatory = $true)][string]$Path)

    for ($attempt = 0; $attempt -lt 10 -and [System.Diagnostics.Stopwatch]::GetTimestamp() -lt $deadline; $attempt++) {
        try {
            return @(Get-Content -LiteralPath $Path -Encoding Default -ErrorAction Stop)
        }
        catch [System.IO.IOException], [System.UnauthorizedAccessException] {
            $remaining = [int][Math]::Floor(($deadline - [System.Diagnostics.Stopwatch]::GetTimestamp()) * 1000 / $frequency)
            if ($remaining -gt 0) { Start-Sleep -Milliseconds ([Math]::Min(100, $remaining)) }
        }
        catch {
            throw
        }
    }

    return @()
}

$args = @(
    "-silent",
    "-$resolvedPil",
    "-$resolvedLog"
)

if ($Conn) {
    $args += "-Conn:`"$Conn`""
}

if ([System.Diagnostics.Stopwatch]::GetTimestamp() -ge $deadline) { exit 2 }
$process = Start-Process `
    -FilePath $resolvedPvi `
    -ArgumentList $args `
    -WorkingDirectory $workDir `
    -WindowStyle Hidden `
    -PassThru

$printedLines = 0
$successSeenAt = $null
$completion = $null
while (-not $process.HasExited) {
    if (Test-Path -LiteralPath $resolvedLog) {
        $lines = Read-LogLines -Path $resolvedLog
        if ($lines.Count -gt $printedLines) {
            $lines[$printedLines..($lines.Count - 1)] | Write-Output
            $printedLines = $lines.Count
        }
        $logText = $lines -join "`n"
        if ($logText -match 'PROCESS FINISHED \(SUCCESS\)' -or $logText -match 'Transfer .* SUCCESSFUL') {
            if (-not $successSeenAt) { $successSeenAt = [System.Diagnostics.Stopwatch]::GetTimestamp() }
            $completion = "success"
        }
        elseif ($logText -match 'PROCESS FINISHED \((FAILURE|ERROR)\)' -or $logText -match 'Transfer .* (FAILED|ERROR)') {
            $completion = "failure"
        }
    }
    if ($completion -eq "failure") { break }
    $now = [System.Diagnostics.Stopwatch]::GetTimestamp()
    if ($completion -eq "success" -and $now - $successSeenAt -ge $SuccessExitGraceSeconds * $frequency) { break }
    $remaining = [int][Math]::Floor(($deadline - $now) * 1000 / $frequency)
    if ($remaining -le 0) { break }
    Start-Sleep -Milliseconds ([Math]::Min(250, $remaining))
    $process.Refresh()
}

if (-not $process.HasExited) {
    if ($DeadlineTicks) {
        try { $process.Kill() }
        catch [System.InvalidOperationException] { if (-not $process.HasExited) { throw } }
    }
    else {
        & taskkill /PID $process.Id /T /F 2>&1 | Out-Null
    }
    if ($completion -eq "success") {
        Write-Output "WARNING: PVITransfer logged success but did not exit; its process tree was cleaned up."
    }
    elseif ($completion -eq "failure") {
        Write-Output "WARNING: PVITransfer logged failure but did not exit; its process tree was cleaned up."
    }
    else {
        Write-Output "WARNING: PVITransfer did not complete within its time budget; termination was requested."
    }
}

if (Test-Path -LiteralPath $resolvedLog) {
    $lines = Read-LogLines -Path $resolvedLog
    if ($lines.Count -gt $printedLines) {
        $lines[$printedLines..($lines.Count - 1)] | Write-Output
    }
}

if ($completion -eq "success") { exit 0 }
if ($completion -eq "failure") { exit 1 }
if ($process.HasExited) { exit $process.ExitCode }
exit 2
