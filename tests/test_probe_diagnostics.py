import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/mcp_server'))
import toolchain


class ProbeDiagnosticsTests(unittest.TestCase):
    def test_budget_is_forwarded_and_partial_probe_is_not_success(self):
        process = unittest.mock.Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps({'ok': False, 'cpu_type': 'X20CP3586'}), '')
        with patch.object(toolchain.subprocess, 'Popen', return_value=process) as popen:
            result = toolchain.run_plc_toolchain('Probe', timeout_seconds=60)
        args = popen.call_args.args[0]
        self.assertEqual(args[args.index('-ProbeWaitSeconds') + 1], '30')
        self.assertFalse(result['ok'])

    def test_timeout_preserves_only_this_operations_disk_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'var').mkdir()
            log = root / 'var/probe_arsim_current.log'
            log.write_text('7: PLCStatus\n', encoding='utf-8')
            (root / 'var/probe_arsim_old.log').write_text('stale success', encoding='utf-8')
            process = unittest.mock.Mock(pid=12345)
            process.communicate.side_effect = [subprocess.TimeoutExpired('Probe', 20), ('', '')]
            with patch.object(toolchain, 'REPO_ROOT', root), patch.object(
                toolchain.subprocess, 'Popen', return_value=process
            ) as popen, patch.object(toolchain, 'terminate_process_tree', return_value={'succeeded': True}):
                with self.assertRaises(toolchain.ToolchainError) as caught:
                    toolchain.run_plc_toolchain('Probe', timeout_seconds=20, operation_id='current')
            self.assertEqual(caught.exception.cleanup['last_log_lines'], ['7: PLCStatus'])
            self.assertEqual(caught.exception.details['log_path'], str(log))
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index('-ProbeWaitSeconds') + 1], '10')

    @unittest.skipUnless(shutil.which('powershell'), 'Windows PowerShell required')
    def test_real_powershell_parser_accepts_empty_logs_and_blank_lines(self):
        script = r'''
$ErrorActionPreference = 'Stop'
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'tools/plc_toolchain.ps1'), [ref]$null, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$fn = $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-PviCommandValue'}, $false)
. ([scriptblock]::Create($fn.Extent.Text))
if ($null -ne (Get-PviCommandValue @() 'CPUType')) { throw 'empty log' }
if ($null -ne (Get-PviCommandValue @('', '') 'CPUType')) { throw 'blank log' }
$lines = @('', '4: CPUType', '', 'X20CP3586', '', 'CPUType SUCCESSFUL', '')
if ((Get-PviCommandValue $lines 'CPUType') -ne 'X20CP3586') { throw 'CPU value' }
if ($null -ne (Get-PviCommandValue $lines 'PLCStatus')) { throw 'missing command' }
'''
        result = subprocess.run(['powershell', '-NoProfile', '-Command', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
