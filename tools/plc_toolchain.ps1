param(
    [ValidateSet("Help", "Build", "StartArsim", "Probe", "DescribePackage", "CheckDownload", "Download", "VerifyOpcUa", "ReadPvi", "RunArsimClosedLoop", "RunVerificationSuite", "GetTargetConfig", "ListTargets")]
    [string]$Command = "Help",

    [string]$ProjectPath = "PrintDemo\Huitong_FrontEval.apj",
    [string]$Config = "Config1",
    [string]$Target = "test_plc",
    [string]$TargetsPath = "tools\plc_targets.local.json",
    [string]$PackagePath = "PrintDemo\Binaries\Config1\X20CP3687X\RUCPackage\RUCPackage.zip",
    [string]$TransferPilPath = "PrintDemo\Binaries\Config1\X20CP3687X\RUCPackage\Transfer.pil",
    [string[]]$OpcUaNodeId,
    [string[]]$PviVariable,
    [switch]$BuildRucPackage,
    [int]$StartWaitSeconds = 3,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath ".").Path
$GeneratedDir = Join-Path $RepoRoot "tools\.generated"

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Read-ToolchainConfig {
    $path = Resolve-RepoPath $TargetsPath
    return Get-Content -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json
}

function Get-TargetConfig {
    param([Parameter(Mandatory = $true)]$ConfigData)

    $targetConfig = $ConfigData.targets.$Target
    if (-not $targetConfig) {
        throw "Target '$Target' was not found in $TargetsPath."
    }
    return $targetConfig
}

function Write-ObjectJson {
    param([Parameter(Mandatory = $true)]$Object)
    $Object | ConvertTo-Json -Depth 16
}

function Save-ToolchainReport {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Report
    )

    $reportsDir = Join-Path $GeneratedDir "reports"
    New-Item -ItemType Directory -Path $reportsDir -Force | Out-Null
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
    $path = Join-Path $reportsDir "$($timestamp)_$Name.json"

    $reportObject = [pscustomobject]$Report
    $reportObject | Add-Member -NotePropertyName report_path -NotePropertyValue $path -Force
    $reportObject | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $path -Encoding UTF8
    return $reportObject
}

function Get-OutputLines {
    param($Output)
    return @($Output | ForEach-Object { $_.ToString() })
}

function Get-OutputTail {
    param(
        [string[]]$Lines,
        [int]$Count = 20
    )

    if (-not $Lines -or $Lines.Count -eq 0) {
        return @()
    }

    return @($Lines | Select-Object -Last $Count)
}

function Convert-JsonProcessOutput {
    param(
        [Parameter(Mandatory = $true)][string]$CommandName,
        [Parameter(Mandatory = $true)][string[]]$Lines,
        [Parameter(Mandatory = $true)][int]$ExitCode
    )

    $text = ($Lines -join [Environment]::NewLine).Trim()
    if (-not $text) {
        return [pscustomobject][ordered]@{
            command = $CommandName
            ok = $false
            process_exit_code = $ExitCode
            error = "The child process did not return JSON output."
            output_tail = @()
        }
    }

    try {
        $parsed = $text | ConvertFrom-Json
        if ($null -eq $parsed.ok) {
            $parsed | Add-Member -NotePropertyName ok -NotePropertyValue ($ExitCode -eq 0) -Force
        }
        $parsed | Add-Member -NotePropertyName process_exit_code -NotePropertyValue $ExitCode -Force
        return $parsed
    }
    catch {
        return [pscustomobject][ordered]@{
            command = $CommandName
            ok = $false
            process_exit_code = $ExitCode
            error = "Failed to parse child process JSON output: $($_.Exception.Message)"
            raw_output = $text
            output_tail = Get-OutputTail $Lines
        }
    }
}

function Invoke-StartArsim {
    param([switch]$Quiet)

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg

    if ($targetConfig.role -notmatch "arsim") {
        throw "Target '$Target' is not marked as an ARsim target."
    }
    if (-not $targetConfig.arsim_loader_exe) {
        throw "Target '$Target' does not define arsim_loader_exe."
    }

    $loader = Resolve-RepoPath $targetConfig.arsim_loader_exe
    if (-not (Test-Path -LiteralPath $loader)) {
        throw "ARsim loader was not found: $loader"
    }

    $existing = Get-Process ar000loader -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $loader } |
        Select-Object -First 1

    $started = $false
    if (-not $existing) {
        $workDir = Split-Path -Parent $loader
        $existing = Start-Process `
            -FilePath $loader `
            -WorkingDirectory $workDir `
            -WindowStyle Hidden `
            -PassThru
        $started = $true
        if ($StartWaitSeconds -gt 0) {
            Start-Sleep -Seconds $StartWaitSeconds
        }
        $existing.Refresh()
    }

    $report = [ordered]@{
        command = "StartArsim"
        ok = $true
        target = $Target
        ip = $targetConfig.ip
        started_new_process = $started
        process_id = $existing.Id
        process_name = $existing.ProcessName
        loader_path = $loader
    }

    if ($Quiet) {
        return [pscustomobject]$report
    }

    Write-ObjectJson $report
}

function Invoke-Build {
    param(
        [switch]$Quiet,
        [switch]$ForceBuildRucPackage
    )

    $cfg = Read-ToolchainConfig
    $buildExe = Resolve-RepoPath $cfg.automation_studio.build_exe
    $project = Resolve-RepoPath $ProjectPath

    if (-not (Test-Path -LiteralPath $buildExe)) {
        throw "BR.AS.Build.exe was not found: $buildExe"
    }
    if (-not (Test-Path -LiteralPath $project)) {
        throw "Project was not found: $project"
    }

    $args = @($project, "-c", $Config)
    $buildRuc = [bool]($BuildRucPackage -or $ForceBuildRucPackage)
    if ($buildRuc) {
        $args += "-buildRUCPackage"
    }

    New-Item -ItemType Directory -Path $GeneratedDir -Force | Out-Null
    $log = Join-Path $GeneratedDir "build_$Config.log"
    $output = & $buildExe @args 2>&1
    $exitCode = $LASTEXITCODE
    $lines = Get-OutputLines $output
    $lines | Set-Content -LiteralPath $log -Encoding UTF8

    $summaryLine = $lines | Where-Object { $_ -match "Build:\s+\d+\s+error\(s\),\s+\d+\s+warning\(s\)" } | Select-Object -Last 1
    $errors = $null
    $warnings = $null
    if ($summaryLine -match "Build:\s+(\d+)\s+error\(s\),\s+(\d+)\s+warning\(s\)") {
        $errors = [int]$Matches[1]
        $warnings = [int]$Matches[2]
    }

    $ok = ($errors -eq 0)
    $warningLines = @($lines | Where-Object { $_ -match "\bwarning\b" })
    $errorLines = @($lines | Where-Object { $_ -match "\berror\b" -and $_ -notmatch "Build:\s+\d+\s+error\(s\)" })
    $report = [ordered]@{
        command = "Build"
        ok = $ok
        process_exit_code = $exitCode
        parsed_errors = $errors
        parsed_warnings = $warnings
        summary = $summaryLine
        project = $project
        config = $Config
        build_ruc_package = $buildRuc
        log_path = $log
        warning_lines = @($warningLines)
        error_lines = @($errorLines)
        output_tail = Get-OutputTail $lines
    }

    if ($Quiet) {
        return [pscustomobject]$report
    }

    Write-ObjectJson $report
    if (-not $ok) {
        exit 1
    }
}

function New-ProbePil {
    param([Parameter(Mandatory = $true)][string]$Ip)

    New-Item -ItemType Directory -Path $GeneratedDir -Force | Out-Null
    $pilPath = Join-Path $GeneratedDir "probe_$Target.pil"
    $lines = @(
        "Connection `"/IF=tcpip`", `"/IP=$Ip /COMT=2500 /AM=* /PT=11169`", `"WT=10`"",
        "CurrentConnection",
        "CPUType",
        "SSWVersion",
        "OnErrorResume",
        "PLCStatus",
        "ClearError"
    )

    Set-Content -LiteralPath $pilPath -Value $lines -Encoding ASCII
    return $pilPath
}

function Get-PviCommandValue {
    param(
        [Parameter(Mandatory = $true)][string[]]$Lines,
        [Parameter(Mandatory = $true)][string]$CommandName
    )

    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match "^\d+:\s+$([regex]::Escape($CommandName))\s*$") {
            for ($j = $i + 1; $j -lt $Lines.Count; $j++) {
                $candidate = $Lines[$j].Trim()
                if (-not $candidate) {
                    continue
                }
                if ($candidate -match "$([regex]::Escape($CommandName))\s+SUCCESSFUL$") {
                    break
                }
                return $candidate
            }
        }
    }

    return $null
}

function Invoke-Probe {
    param([switch]$Quiet)

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $wrapper = Resolve-RepoPath "tools\invoke_pvitransfer_silent.ps1"
    $pviTransfer = Resolve-RepoPath $cfg.automation_studio.pvi_transfer_exe
    $pil = New-ProbePil $targetConfig.ip
    $log = Join-Path $GeneratedDir "probe_$Target.log"

    $output = & powershell -NoProfile -ExecutionPolicy Bypass `
        -File $wrapper `
        -PilPath $pil `
        -LogPath $log `
        -PviTransferPath $pviTransfer 2>&1
    $exitCode = $LASTEXITCODE

    $lines = @($output | ForEach-Object { $_.ToString() })
    $report = [ordered]@{
        command = "Probe"
        ok = (($exitCode -eq 0) -or ((Get-PviCommandValue $lines "CPUType") -and (Get-PviCommandValue $lines "SSWVersion")))
        process_exit_code = $exitCode
        target = $Target
        ip = $targetConfig.ip
        role = $targetConfig.role
        cpu_type = Get-PviCommandValue $lines "CPUType"
        ar_version = Get-PviCommandValue $lines "SSWVersion"
        plc_status = Get-PviCommandValue $lines "PLCStatus"
        log_path = $log
        pil_path = $pil
        output_tail = Get-OutputTail $lines
    }

    if ($Quiet) {
        return [pscustomobject]$report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

function Get-PackageInfo {
    $package = Resolve-RepoPath $PackagePath
    if (-not (Test-Path -LiteralPath $package)) {
        throw "RUC package was not found: $package"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($package)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName -eq "ProjectInformation.xml" } | Select-Object -First 1
        if (-not $entry) {
            throw "ProjectInformation.xml was not found inside $package."
        }

        $reader = New-Object System.IO.StreamReader($entry.Open(), [System.Text.Encoding]::UTF8)
        try {
            [xml]$xml = $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $zip.Dispose()
    }

    if (-not $xml.ProjectInformation) {
        throw "ProjectInformation.xml was not found inside $package."
    }

    $info = $xml.ProjectInformation
    return [pscustomobject][ordered]@{
        command = "DescribePackage"
        ok = $true
        package_path = $package
        project_information_path = "zip://ProjectInformation.xml"
        configuration_id = [string]$info.ConfigurationID
        config_version = [string]$info.ConfigVersion
        cpu_type = [string]$info.CPUType
        compatible_cpu_code = [string]$info.CompatibleCpuCode
        order_number = [string]$info.OrderNumber
        runtime_type = [string]$info.RuntimeType
        ar_version = [string]$info.ARVersion
        br_module_system = [string]$info.BRModuleSystem
        additional_zip_file_name_prefix = [string]$info.AdditionalZipFileNamePrefix
    }
}

function Invoke-DescribePackage {
    param([switch]$Quiet)

    $info = Get-PackageInfo
    if ($Quiet) {
        return $info
    }

    Write-ObjectJson $info
}

function Test-DownloadSafety {
    param([switch]$Quiet)

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $packageInfo = Get-PackageInfo
    $probe = Invoke-Probe -Quiet

    $reasons = New-Object System.Collections.Generic.List[string]
    $isArsimPackage = ($packageInfo.cpu_type -eq "AR000" -or $packageInfo.runtime_type -match "AR Simulation")
    $isArsimTarget = ($targetConfig.role -match "arsim")

    if (-not $targetConfig.allow_auto_download) {
        $reasons.Add("Target '$Target' does not allow automatic download.")
    }
    if ($targetConfig.role -match "production") {
        $reasons.Add("Target '$Target' is marked as production.")
    }
    if ($probe.process_exit_code -ne 0 -or -not $probe.cpu_type) {
        $reasons.Add("Target probe did not return a valid CPU type.")
    }
    if ($isArsimPackage -and -not $isArsimTarget) {
        $reasons.Add("RUC package is for ARsim, but target '$Target' is not marked as ARsim.")
    }
    if ((-not $isArsimPackage) -and $probe.cpu_type -and $packageInfo.cpu_type -and ($packageInfo.cpu_type -ne $probe.cpu_type)) {
        $reasons.Add("RUC package CPU '$($packageInfo.cpu_type)' does not match target CPU '$($probe.cpu_type)'.")
    }

    $ok = ($reasons.Count -eq 0)
    $report = [ordered]@{
        command = "CheckDownload"
        ok = $ok
        target = $Target
        target_ip = $targetConfig.ip
        target_role = $targetConfig.role
        target_allow_auto_download = [bool]$targetConfig.allow_auto_download
        package = $packageInfo
        probe = $probe
        reasons = @($reasons)
    }

    if ($Quiet) {
        return [pscustomobject]$report
    }

    Write-ObjectJson $report
    if (-not $ok) {
        exit 1
    }
}

function Invoke-Download {
    param(
        [switch]$Quiet,
        [switch]$ForceExecute
    )

    $check = Test-DownloadSafety -Quiet
    if (-not $check.ok) {
        $report = [ordered]@{
            command = "Download"
            ok = $false
            target = $Target
            executed = $false
            safety_check = $check
            reasons = @($check.reasons)
            error = "Download safety check failed. Refusing to download."
        }
        if ($Quiet) {
            return [pscustomobject]$report
        }
        Write-ObjectJson $report
        exit 2
    }

    $shouldExecute = [bool]($Execute -or $ForceExecute)
    if (-not $shouldExecute) {
        $report = [ordered]@{
            command = "Download"
            ok = $true
            target = $Target
            executed = $false
            safety_check = $check
            message = "Download safety check passed, but -Execute was not specified. No download performed."
        }
        if ($Quiet) {
            return [pscustomobject]$report
        }
        Write-ObjectJson $report
        return
    }

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $wrapper = Resolve-RepoPath "tools\invoke_pvitransfer_silent.ps1"
    $pviTransfer = Resolve-RepoPath $cfg.automation_studio.pvi_transfer_exe
    $pil = Resolve-RepoPath $TransferPilPath
    $log = Join-Path (Split-Path -Parent $pil) "pvi_download_$Target.log"
    $conn = "'/IF=tcpip', '/IP=$($targetConfig.ip) /COMT=2500 /AM=* /PT=11169', 'WT=60', 'IGNORE'"

    $output = & powershell -NoProfile -ExecutionPolicy Bypass `
        -File $wrapper `
        -PilPath $pil `
        -LogPath $log `
        -PviTransferPath $pviTransfer `
        -Conn $conn 2>&1
    $downloadExitCode = $LASTEXITCODE
    $lines = Get-OutputLines $output
    $downloadOk = (($downloadExitCode -eq 0) -and (($lines -join "`n") -match "SUCCESSFUL"))
    $verification = $null

    if ($downloadOk -and $cfg.opcua.verify_after_download -eq $true) {
        $verification = Invoke-VerifyOpcUa -Quiet
    }
    elseif ($downloadOk -and $cfg.pvi.verify_after_download -eq $true) {
        $verification = Invoke-ReadPvi -Quiet
    }

    $ok = $downloadOk
    if ($verification -and $verification.ok -eq $false) {
        $ok = $false
    }

    $report = [ordered]@{
        command = "Download"
        ok = $ok
        target = $Target
        target_ip = $targetConfig.ip
        executed = $true
        safety_check = $check
        download_ok = $downloadOk
        download_process_exit_code = $downloadExitCode
        log_path = $log
        output_tail = Get-OutputTail $lines
        verification = $verification
    }

    if ($Quiet) {
        return [pscustomobject]$report
    }

    Write-ObjectJson $report
    if (-not $ok) {
        if ($downloadExitCode -ne 0) {
            exit $downloadExitCode
        }
        exit 1
    }
}

function Invoke-RunVerificationSuite {
    param([switch]$Quiet)

    $opcua = Invoke-VerifyOpcUa -Quiet
    $pvi = $null
    $method = "opcua"
    $ok = [bool]$opcua.ok

    if (-not $ok) {
        $pvi = Invoke-ReadPvi -Quiet
        $method = "pvi"
        $ok = [bool]$pvi.ok
    }

    $report = Save-ToolchainReport -Name "verification_$Target" -Report ([ordered]@{
        command = "RunVerificationSuite"
        ok = $ok
        target = $Target
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        method = $method
        opcua = $opcua
        pvi = $pvi
    })

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $ok) {
        exit 1
    }
}

function Invoke-RunArsimClosedLoop {
    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    if ($targetConfig.role -notmatch "arsim") {
        throw "RunArsimClosedLoop only supports ARsim targets. Target '$Target' has role '$($targetConfig.role)'."
    }

    $build = Invoke-Build -Quiet -ForceBuildRucPackage
    $start = $null
    $probe = $null
    $package = $null
    $check = $null
    $download = $null
    $verification = $null

    if ($build.ok) {
        $start = Invoke-StartArsim -Quiet
    }
    if ($start -and $start.ok) {
        $probe = Invoke-Probe -Quiet
    }
    if ($probe -and $probe.ok) {
        $package = Invoke-DescribePackage -Quiet
        $check = Test-DownloadSafety -Quiet
    }
    if ($check -and $check.ok) {
        $download = Invoke-Download -Quiet
        if ($download.executed -and $download.ok) {
            $verification = $download.verification
            if (-not $verification) {
                $verification = Invoke-RunVerificationSuite -Quiet
            }
        }
    }

    $ok = [bool]($build.ok -and $start.ok -and $probe.ok -and $package.ok -and $check.ok -and $download.ok)
    if ($download -and $download.executed -and $verification) {
        $ok = [bool]($ok -and $verification.ok)
    }

    $report = Save-ToolchainReport -Name "closed_loop_$Target" -Report ([ordered]@{
        command = "RunArsimClosedLoop"
        ok = $ok
        target = $Target
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        build = $build
        start_arsim = $start
        target_probe = $probe
        package = $package
        download_check = $check
        download = $download
        verification = $verification
    })

    Write-ObjectJson $report
    if (-not $ok) {
        exit 1
    }
}

function Invoke-GetTargetConfig {
    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $report = [ordered]@{
        command = "GetTargetConfig"
        ok = $true
        target = $Target
        target_config = $targetConfig
        opcua = $cfg.opcua
        pvi = $cfg.pvi
    }

    Write-ObjectJson $report
}

function Invoke-ListTargets {
    $cfg = Read-ToolchainConfig
    $targets = @(
        foreach ($item in $cfg.targets.PSObject.Properties) {
            [ordered]@{
                name = $item.Name
                ip = $item.Value.ip
                role = $item.Value.role
                allow_auto_download = [bool]$item.Value.allow_auto_download
            }
        }
    )

    $report = [ordered]@{
        command = "ListTargets"
        ok = $true
        targets = $targets
    }

    Write-ObjectJson $report
}

function Invoke-VerifyOpcUa {
    param([switch]$Quiet)

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $port = 4840
    if ($cfg.opcua.endpoint_port) {
        $port = [int]$cfg.opcua.endpoint_port
    }

    $warnings = @()
    if ($cfg.opcua.auto_expose_all -eq $true) {
        $warnings += "opcua.auto_expose_all is enabled. This is not recommended for customer equipment."
    }

    $nodes = @()
    if ($OpcUaNodeId -and $OpcUaNodeId.Count -gt 0) {
        $nodes = @($OpcUaNodeId)
    }
    elseif ($cfg.opcua.validation_node_ids) {
        $nodes = @($cfg.opcua.validation_node_ids)
    }

    if ($nodes.Count -eq 0) {
        throw "No OPC UA validation nodes configured. Set opcua.validation_node_ids or pass -OpcUaNodeId."
    }

    $endpoint = "opc.tcp://$($targetConfig.ip):$port"
    $script = Resolve-RepoPath "tools\opcua_read.py"
    New-Item -ItemType Directory -Path $GeneratedDir -Force | Out-Null
    $nodesFile = Join-Path $GeneratedDir "opcua_nodes_$Target.json"
    ConvertTo-Json @($nodes) -Depth 4 | Set-Content -LiteralPath $nodesFile -Encoding UTF8

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & python $script --endpoint $endpoint --nodes-file $nodesFile 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    $lines = Get-OutputLines $output
    $report = Convert-JsonProcessOutput -CommandName "VerifyOpcUa" -Lines $lines -ExitCode $exitCode
    $report | Add-Member -NotePropertyName target -NotePropertyValue $Target -Force
    $report | Add-Member -NotePropertyName nodes_file -NotePropertyValue $nodesFile -Force
    $report | Add-Member -NotePropertyName warnings -NotePropertyValue @($warnings) -Force

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

function Invoke-ReadPvi {
    param([switch]$Quiet)

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg

    if ($cfg.pvi.enabled -eq $false) {
        throw "PVI reading is disabled in pvi.enabled."
    }

    $variables = @()
    if ($PviVariable -and $PviVariable.Count -gt 0) {
        $variables = @(
            foreach ($item in $PviVariable) {
                $item -split "," | Where-Object { $_.Trim().Length -gt 0 } | ForEach-Object { $_.Trim() }
            }
        )
    }
    elseif ($cfg.pvi.validation_variables) {
        $variables = @($cfg.pvi.validation_variables)
    }

    if ($variables.Count -eq 0) {
        throw "No PVI variables configured. Set pvi.validation_variables or pass -PviVariable."
    }

    $script = Resolve-RepoPath "tools\pvi_read.py"
    New-Item -ItemType Directory -Path $GeneratedDir -Force | Out-Null
    $variablesFile = Join-Path $GeneratedDir "pvi_variables_$Target.json"
    ConvertTo-Json @($variables) -Depth 8 | Set-Content -LiteralPath $variablesFile -Encoding UTF8

    $args = @(
        $script,
        "--ip", $targetConfig.ip,
        "--variables-file", $variablesFile,
        "--cpu-name", $Target
    )
    if ($cfg.pvi.pvi_dll_dir) {
        $args += @("--pvi-dll-dir", (Resolve-RepoPath $cfg.pvi.pvi_dll_dir))
    }

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & python @args 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    $lines = Get-OutputLines $output
    $report = Convert-JsonProcessOutput -CommandName "ReadPvi" -Lines $lines -ExitCode $exitCode
    $report | Add-Member -NotePropertyName target -NotePropertyValue $Target -Force
    $report | Add-Member -NotePropertyName variables_file -NotePropertyValue $variablesFile -Force

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

try {
switch ($Command) {
    "Help" {
        @"
Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Build -BuildRucPackage
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command StartArsim -Target arsim
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Probe -Target test_plc
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command DescribePackage
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command CheckDownload -Target test_plc
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command Download -Target test_plc -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command VerifyOpcUa -Target arsim
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ReadPvi -Target arsim
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ReadPvi -Target arsim -PviVariable 'gstHmi.stOutputs.diSImage,SVG:strTransform'
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command RunVerificationSuite -Target arsim
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command RunArsimClosedLoop -Target arsim -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ListTargets
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command GetTargetConfig -Target test_plc
"@ | Write-Output
    }
    "Build" { Invoke-Build }
    "StartArsim" { Invoke-StartArsim }
    "Probe" { Invoke-Probe }
    "DescribePackage" { Invoke-DescribePackage }
    "CheckDownload" { Test-DownloadSafety }
    "Download" { Invoke-Download }
    "VerifyOpcUa" { Invoke-VerifyOpcUa }
    "ReadPvi" { Invoke-ReadPvi }
    "RunArsimClosedLoop" { Invoke-RunArsimClosedLoop }
    "RunVerificationSuite" { Invoke-RunVerificationSuite }
    "GetTargetConfig" { Invoke-GetTargetConfig }
    "ListTargets" { Invoke-ListTargets }
}
}
catch {
    $report = [ordered]@{
        command = $Command
        ok = $false
        error = $_.Exception.Message
        category = $_.CategoryInfo.Category.ToString()
        target = $Target
    }
    Write-ObjectJson $report
    exit 1
}
