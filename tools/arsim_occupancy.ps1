param([string]$Addresses = '127.0.0.1,127.0.0.2,127.0.0.3,127.0.0.4,127.0.0.5')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'arsim_occupancy_functions.ps1')
$config = [pscustomobject]@{
    pipeName = 'BR.ARsimPool.v2'; sampleSeconds = 2; staleSeconds = 8
    slots = @($Addresses -split ','); tcpPorts = @(80, 81, 4840, 11169); udpPorts = @(); pviPort = 11169
}
Test-Configuration $config
Get-Occupancy $config | ConvertTo-Json -Depth 10 -Compress
