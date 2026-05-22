param(
    [ValidateSet("Help", "Build", "StartArsim", "Probe", "DescribePackage", "CheckDownload", "Download", "VerifyOpcUa", "ReadPvi")]
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
    $Object | ConvertTo-Json -Depth 8
}

function Invoke-StartArsim {
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

    Write-ObjectJson $report
}

function Invoke-Build {
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
    if ($BuildRucPackage) {
        $args += "-buildRUCPackage"
    }

    $output = & $buildExe @args 2>&1
    $exitCode = $LASTEXITCODE
    $output | Write-Output

    $summaryLine = $output | Where-Object { $_ -match "Build:\s+\d+\s+error\(s\),\s+\d+\s+warning\(s\)" } | Select-Object -Last 1
    $errors = $null
    $warnings = $null
    if ($summaryLine -match "Build:\s+(\d+)\s+error\(s\),\s+(\d+)\s+warning\(s\)") {
        $errors = [int]$Matches[1]
        $warnings = [int]$Matches[2]
    }

    $ok = ($errors -eq 0)
    $report = [ordered]@{
        command = "Build"
        ok = $ok
        process_exit_code = $exitCode
        parsed_errors = $errors
        parsed_warnings = $warnings
        summary = $summaryLine
        project = $project
        config = $Config
        build_ruc_package = [bool]$BuildRucPackage
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
    if (-not $Quiet) {
        $output | Write-Output
    }

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
    }

    if ($Quiet) {
        return [pscustomobject]$report
    }

    Write-ObjectJson $report
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
}

function Invoke-Download {
    $check = Test-DownloadSafety -Quiet
    if (-not $check.ok) {
        Write-Error "Download safety check failed. Refusing to download."
        exit 2
    }

    if (-not $Execute) {
        Write-Output "Download safety check passed, but -Execute was not specified. No download performed."
        return
    }

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $wrapper = Resolve-RepoPath "tools\invoke_pvitransfer_silent.ps1"
    $pviTransfer = Resolve-RepoPath $cfg.automation_studio.pvi_transfer_exe
    $pil = Resolve-RepoPath $TransferPilPath
    $log = Join-Path (Split-Path -Parent $pil) "pvi_download_$Target.log"
    $conn = "'/IF=tcpip', '/IP=$($targetConfig.ip) /COMT=2500 /AM=* /PT=11169', 'WT=60', 'IGNORE'"

    & powershell -NoProfile -ExecutionPolicy Bypass `
        -File $wrapper `
        -PilPath $pil `
        -LogPath $log `
        -PviTransferPath $pviTransfer `
        -Conn $conn
    $downloadExitCode = $LASTEXITCODE
    if ($downloadExitCode -ne 0) {
        exit $downloadExitCode
    }

    if ($cfg.opcua.verify_after_download -eq $true) {
        Write-Output "Running OPC UA verification after download..."
        Invoke-VerifyOpcUa
    }
    elseif ($cfg.pvi.verify_after_download -eq $true) {
        Write-Output "Running PVI verification after download..."
        Invoke-ReadPvi
    }
}

function Invoke-VerifyOpcUa {
    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $port = 4840
    if ($cfg.opcua.endpoint_port) {
        $port = [int]$cfg.opcua.endpoint_port
    }

    if ($cfg.opcua.auto_expose_all -eq $true) {
        Write-Warning "opcua.auto_expose_all is enabled. This is not recommended for customer equipment."
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

    & python $script --endpoint $endpoint --nodes-file $nodesFile
    exit $LASTEXITCODE
}

function Invoke-ReadPvi {
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

    & python @args
    exit $LASTEXITCODE
}

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
}
