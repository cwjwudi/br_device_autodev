param(
    [Parameter(Mandatory = $true)]
    [string]$PilPath,

    [string]$LogPath,

    [string]$PviTransferPath = "D:\BRAutomation\AS65\PVI6\PVI\Tools\PVITransfer\PVITransfer.exe",

    [string]$Conn
)

$ErrorActionPreference = "Stop"

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

    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        try {
            return @(Get-Content -LiteralPath $Path -Encoding Default -ErrorAction Stop)
        }
        catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 100
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

$process = Start-Process `
    -FilePath $resolvedPvi `
    -ArgumentList $args `
    -WorkingDirectory $workDir `
    -WindowStyle Hidden `
    -PassThru

$printedLines = 0
while (-not $process.HasExited) {
    if (Test-Path -LiteralPath $resolvedLog) {
        $lines = Read-LogLines -Path $resolvedLog
        if ($lines.Count -gt $printedLines) {
            $lines[$printedLines..($lines.Count - 1)] | Write-Output
            $printedLines = $lines.Count
        }
    }
    Start-Sleep -Milliseconds 250
    $process.Refresh()
}

if (Test-Path -LiteralPath $resolvedLog) {
    $lines = Read-LogLines -Path $resolvedLog
    if ($lines.Count -gt $printedLines) {
        $lines[$printedLines..($lines.Count - 1)] | Write-Output
    }
}

exit $process.ExitCode
