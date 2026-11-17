from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("powershell"), reason="Windows PowerShell required")
def test_download_defaults_and_force_are_target_scoped() -> None:
    script = r'''
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'tools/plc_toolchain.ps1'), [ref]$null, [ref]$null)
foreach ($name in @('Get-TargetConfig', 'Test-DownloadSafety')) {
    $fn = $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $false)
    . ([scriptblock]::Create($fn.Extent.Text))
}
$TargetsPath = 'test.json'
$Target = 'device'
$Config = 'Config'
$ForceArsimDownload = $false
$BypassDownloadSafety = $false
$script:cfg = '{"targets":{"device":{"ip":"127.0.0.1","role":"arsim"}}}' | ConvertFrom-Json
function Read-ToolchainConfig { return $script:cfg }
function Get-PackageInfo { return [pscustomobject]@{cpu_type='AR000';runtime_type='AR Simulation';transfer_policy=@{available=$false}} }
function Invoke-Probe { param([switch]$Quiet) return [pscustomobject]@{ok=$true;cpu_type='AR000'} }
if (-not (Get-TargetConfig $script:cfg).allow_auto_download) { throw 'ARsim should allow download by default' }
if (-not (Test-DownloadSafety -Quiet).ok) { throw 'ARsim should pass the basic download guard' }
$script:cfg = '{"targets":{"device":{"ip":"192.0.2.10","role":"dedicated_test_plc"}}}' | ConvertFrom-Json
function Get-PackageInfo { return [pscustomobject]@{cpu_type='X20';runtime_type='Physical';transfer_policy=@{available=$false}} }
function Invoke-Probe { param([switch]$Quiet) return [pscustomobject]@{ok=$true;cpu_type='X20'} }
if ((Get-TargetConfig $script:cfg).allow_auto_download) { throw 'Physical download must default to disabled' }
if ((Test-DownloadSafety -Quiet).ok) { throw 'Physical download must be blocked by default' }
$script:cfg.targets.device.allow_auto_download = $true
if (-not (Test-DownloadSafety -Quiet).ok) { throw 'Explicit physical download permission should be honored' }
$ForceArsimDownload = $true
if ((Test-DownloadSafety -Quiet).ok) { throw 'ARsim force must not apply to physical targets' }
$ForceArsimDownload = $false
$BypassDownloadSafety = $true
if ((Test-DownloadSafety -Quiet).ok) { throw 'Bypass must not apply to physical targets' }
$BypassDownloadSafety = $false
$script:cfg = '{"targets":{"device":{"ip":"192.0.2.10","role":"production","allow_auto_download":true}}}' | ConvertFrom-Json
if ((Test-DownloadSafety -Quiet).ok) { throw 'Production download must remain blocked' }
$script:cfg = '{"targets":{"device":{"ip":"192.0.2.10","role":"dedicated_test_plc","allow_auto_download":"false"}}}' | ConvertFrom-Json
try { Get-TargetConfig $script:cfg; throw 'Non-boolean download permission was accepted' }
catch { if ($_.Exception.Message -notmatch 'must be a boolean') { throw } }
$script:cfg = '{"targets":{"device":{"ip":"192.0.2.10","role":"arsim"}}}' | ConvertFrom-Json
try { Get-TargetConfig $script:cfg; throw 'Physical IP was accepted as ARsim' }
catch { if ($_.Exception.Message -notmatch 'loopback') { throw } }
exit 0
'''
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
