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
        $lines = Get-Content -LiteralPath $resolvedLog -Encoding Default
        if ($lines.Count -gt $printedLines) {
            $lines[$printedLines..($lines.Count - 1)] | Write-Output
            $printedLines = $lines.Count
        }
    }
    Start-Sleep -Milliseconds 250
    $process.Refresh()
}

if (Test-Path -LiteralPath $resolvedLog) {
    $lines = Get-Content -LiteralPath $resolvedLog -Encoding Default
    if ($lines.Count -gt $printedLines) {
        $lines[$printedLines..($lines.Count - 1)] | Write-Output
    }
}

exit $process.ExitCode
