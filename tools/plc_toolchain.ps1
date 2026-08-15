param(
    [ValidateSet("Help", "Build", "StartArsim", "Probe", "DescribePackage", "CheckDownload", "Download", "VerifyOpcUa", "ReadPvi", "ReadLogger", "WritePvi", "RunIoTestCase", "RunTestSuite", "ResetTestHarness", "RunArsimClosedLoop", "RunVerificationSuite", "CheckApplicationReadiness", "GetTargetConfig", "ListTargets")]
    [string]$Command = "Help",

    [string]$ProjectPath = "",
    [string]$Config = "",
    [string]$Target = "arsim",
    [string]$TargetsPath = "config\targets\default-safe.json",
    [string]$Toolchain = "",
    [string]$ToolchainsPath = "config\toolchains\toolchains.json",
    [string]$PackagePath = "",
    [string]$TransferPilPath = "",
    [string[]]$OpcUaNodeId,
    [string[]]$PviVariable,
    [string]$LoggerType = "System",
    [string]$LoggerName = '$arlogsys',
    [string]$Format = ".html",
    [string]$OutputPath,
    [string]$WritesPath,
    [string]$SuitePath = "tests\plc\lqr_io_tests.json",
    [string]$CaseName,
    [string]$OperationId = "",
    [int]$SettleMs = 100,
    [switch]$BuildRucPackage,
    [int]$StartWaitSeconds = 3,
    [switch]$ForceArsimDownload,
    [switch]$BypassDownloadSafety,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath ".").Path
$GeneratedDir = Join-Path $RepoRoot "var"
if (-not $OperationId) {
    $OperationId = [guid]::NewGuid().ToString("N")
}

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Resolve-RucPackagePath {
    if ($PackagePath) {
        return Resolve-RepoPath $PackagePath
    }

    if (-not $ProjectPath) {
        return Resolve-RepoPath (Join-Path "Binaries" (Join-Path $Config "RUCPackage\RUCPackage.zip"))
    }

    $projectDir = Split-Path -Parent $ProjectPath
    if (-not $projectDir) { $projectDir = "." }
    $binariesDir = Resolve-RepoPath (Join-Path $projectDir (Join-Path "Binaries" $Config))
    $matches = @()
    if (Test-Path -LiteralPath $binariesDir) {
        $matches = @(Get-ChildItem -LiteralPath $binariesDir -Recurse -Filter "RUCPackage.zip" -File |
            Sort-Object LastWriteTime -Descending)
    }
    if ($matches.Count -gt 0) {
        return $matches[0].FullName
    }

    return Resolve-RepoPath (Join-Path $projectDir (Join-Path "Binaries" (Join-Path $Config "RUCPackage\RUCPackage.zip")))
}

function Resolve-TransferPilPath {
    if ($TransferPilPath) {
        return Resolve-RepoPath $TransferPilPath
    }

    $package = Resolve-RucPackagePath
    $packageDir = Split-Path -Parent $package
    return Join-Path $packageDir "Transfer.pil"
}

function Resolve-ArsimLoaderPath {
    param([Parameter(Mandatory = $true)]$TargetConfig)

    $configured = [string]$TargetConfig.arsim_loader_exe
    if ($configured -and $configured -notlike '<*') {
        return Resolve-RepoPath $configured
    }
    if (-not $ProjectPath -or -not $Config) {
        throw "ARSIM_LOADER_REQUIRED: provide ProjectPath and Config so the generated ARsim loader can be resolved."
    }

    $resolvedProject = Resolve-RepoPath $ProjectPath
    $projectDir = if (Test-Path -LiteralPath $resolvedProject -PathType Container) {
        $resolvedProject
    }
    else {
        Split-Path -Parent $resolvedProject
    }
    $simulationRoot = Join-Path $projectDir (Join-Path "Temp\Simulation" $Config)
    $matches = @()
    if (Test-Path -LiteralPath $simulationRoot -PathType Container) {
        $matches = @(Get-ChildItem -LiteralPath $simulationRoot -Recurse -Filter "ar000loader.exe" -File)
    }
    if ($matches.Count -eq 1) {
        return $matches[0].FullName
    }
    if ($matches.Count -gt 1) {
        throw "ARSIM_LOADER_AMBIGUOUS: found $($matches.Count) loaders below '$simulationRoot'; configure arsim_loader_exe explicitly."
    }
    throw "ARSIM_LOADER_REQUIRED: no generated ar000loader.exe was found below '$simulationRoot'; build the selected simulation config first."
}

function Get-ProjectConfigurationMetadata {
    $report = [ordered]@{
        automation_studio_config = $Config
        configuration_id = $null
        configuration_id_source = "unavailable"
        hardware_path = $null
    }
    if (-not $ProjectPath -or -not $Config) {
        return [pscustomobject]$report
    }

    $resolvedProject = Resolve-RepoPath $ProjectPath
    $projectDir = if (Test-Path -LiteralPath $resolvedProject -PathType Container) {
        $resolvedProject
    }
    else {
        Split-Path -Parent $resolvedProject
    }
    $hardwarePath = Join-Path $projectDir (Join-Path "Physical" (Join-Path $Config "Hardware.hw"))
    $report.hardware_path = $hardwarePath
    if (-not (Test-Path -LiteralPath $hardwarePath -PathType Leaf)) {
        return [pscustomobject]$report
    }

    [xml]$hardware = Get-Content -LiteralPath $hardwarePath -Encoding UTF8
    $configurationNode = $hardware.SelectSingleNode("//*[local-name()='Parameter' and @ID='ConfigurationID']")
    if ($configurationNode -and $configurationNode.Value) {
        $report.configuration_id = [string]$configurationNode.Value
        $report.configuration_id_source = "project_hardware"
    }
    return [pscustomobject]$report
}

function Test-ArsimProjectBinding {
    param(
        [Parameter(Mandatory = $true)]$TargetConfig,
        [Parameter(Mandatory = $true)]$ProjectMetadata
    )

    if ($TargetConfig.role -notmatch "arsim" -or -not $TargetConfig.arsim_loader_exe -or -not $ProjectPath -or -not $Config) {
        return $false
    }
    if (-not $ProjectMetadata.configuration_id) {
        return $false
    }

    $resolvedProject = Resolve-RepoPath $ProjectPath
    $projectDir = if (Test-Path -LiteralPath $resolvedProject -PathType Container) {
        $resolvedProject
    }
    else {
        Split-Path -Parent $resolvedProject
    }
    $simulationDir = [System.IO.Path]::GetFullPath((Join-Path $projectDir (Join-Path "Temp\Simulation" $Config))).TrimEnd('\') + '\'
    $loaderPath = [System.IO.Path]::GetFullPath((Resolve-ArsimLoaderPath -TargetConfig $TargetConfig))
    return $loaderPath.StartsWith($simulationDir, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-BoundArsimMediaMetadata {
    param(
        [Parameter(Mandatory = $true)]$TargetConfig,
        [Parameter(Mandatory = $true)]$ProjectMetadata
    )

    $report = [ordered]@{
        bound = $false
        media_root = $null
        config_version = $null
        config_version_source = "unavailable"
        partition_layout = $null
        partition_layout_source = "unavailable"
        partition_layout_path = $null
    }
    if (-not (Test-ArsimProjectBinding -TargetConfig $TargetConfig -ProjectMetadata $ProjectMetadata)) {
        return [pscustomobject]$report
    }

    $loaderPath = [System.IO.Path]::GetFullPath((Resolve-ArsimLoaderPath -TargetConfig $TargetConfig))
    $mediaRoot = Split-Path -Parent $loaderPath
    $report.bound = $true
    $report.media_root = $mediaRoot

    $versionPath = Join-Path $mediaRoot "RPSHD\SYSROM\prjver.sys"
    if (Test-Path -LiteralPath $versionPath -PathType Leaf) {
        $versionBytes = [System.IO.File]::ReadAllBytes($versionPath)
        $versionText = [System.Text.Encoding]::ASCII.GetString($versionBytes).Split([char]0)[0].Trim()
        if ($versionText) {
            $report.config_version = $versionText
            $report.config_version_source = "bound_arsim_media"
        }
    }

    $partitionPath = Join-Path $mediaRoot "SYSTEM\TOC\fscfg.xml"
    if (Test-Path -LiteralPath $partitionPath -PathType Leaf) {
        $report.partition_layout = (Get-FileHash -LiteralPath $partitionPath -Algorithm SHA256).Hash
        $report.partition_layout_source = "bound_arsim_media_sha256"
        $report.partition_layout_path = $partitionPath
    }
    return [pscustomobject]$report
}

function Get-TransferPolicy {
    $pilPath = Resolve-TransferPilPath
    $report = [ordered]@{
        path = $pilPath
        available = $false
        install_mode = $null
        install_restriction = $null
        ignore_version = $null
    }
    if (-not (Test-Path -LiteralPath $pilPath -PathType Leaf)) {
        return [pscustomobject]$report
    }

    $content = Get-Content -LiteralPath $pilPath -Raw -Encoding UTF8
    $transferMatch = [regex]::Match($content, 'Transfer\s+"[^"]+"\s*,\s*"([^"]*)"', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $transferMatch.Success) {
        return [pscustomobject]$report
    }

    $options = $transferMatch.Groups[1].Value
    foreach ($optionMatch in [regex]::Matches($options, '(?<name>[A-Za-z][A-Za-z0-9]*)=(?<value>[^\s"]+)')) {
        $name = $optionMatch.Groups['name'].Value
        $value = $optionMatch.Groups['value'].Value
        switch -Regex ($name) {
            '^InstallMode$' { $report.install_mode = $value }
            '^InstallRestriction$' { $report.install_restriction = $value }
            '^IgnoreVersion$' { $report.ignore_version = ($value -eq '1' -or $value -ieq 'true') }
        }
    }
    $report.available = [bool]$report.install_mode
    return [pscustomobject]$report
}

function Read-ToolchainConfig {
    $path = Resolve-RepoPath $TargetsPath
    return Get-Content -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json
}

function Read-GlobalToolchainRegistry {
    $requested = Resolve-RepoPath $ToolchainsPath
    $local = Resolve-RepoPath "config\local\toolchains.json"
    if ($ToolchainsPath -eq "config\toolchains\toolchains.json" -and (Test-Path -LiteralPath $local)) {
        $requested = $local
    }
    if (-not (Test-Path -LiteralPath $requested)) {
        throw "Global toolchain registry was not found: $requested"
    }
    return [pscustomobject]@{
        path = $requested
        data = Get-Content -LiteralPath $requested -Encoding UTF8 | ConvertFrom-Json
    }
}

function Get-SelectedToolchain {
    $registry = Read-GlobalToolchainRegistry
    $selected = if ($Toolchain) { $Toolchain } else { [string]$registry.data.default_toolchain }
    if (-not $selected) {
        throw "No toolchain was selected and the registry has no default_toolchain."
    }
    $entry = $registry.data.toolchains.$selected
    if (-not $entry) {
        $choices = @($registry.data.toolchains.PSObject.Properties.Name) -join ", "
        throw "Toolchain '$selected' was not found in $($registry.path). Available: $choices"
    }
    if ($entry.enabled -eq $false) {
        throw "Toolchain '$selected' is disabled in $($registry.path)."
    }
    if ($entry.family -notin @("AS4", "AS6")) {
        throw "Toolchain '$selected' has unsupported family '$($entry.family)'."
    }
    $entry | Add-Member -NotePropertyName id -NotePropertyValue $selected -Force
    $entry | Add-Member -NotePropertyName registry_path -NotePropertyValue $registry.path -Force
    return $entry
}

function Get-TargetConfig {
    param([Parameter(Mandatory = $true)]$ConfigData)

    $targetConfig = $ConfigData.targets.$Target
    if (-not $targetConfig) {
        throw "Target '$Target' was not found in $TargetsPath."
    }
    return $targetConfig
}

function Invoke-AuthoritativeAccessPolicy {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("describe", "pvi_read", "pvi_write", "opcua_read")][string]$Operation,
        [Parameter(Mandatory = $true)]$Items,
        [bool]$Explicit = $false,
        [bool]$ExecuteRequest = $false
    )

    $script = Resolve-RepoPath "tools\plc_access_policy_cli.py"
    New-Item -ItemType Directory -Path $GeneratedDir -Force | Out-Null
    $itemsPath = Join-Path $GeneratedDir "access_policy_items_$([guid]::NewGuid().ToString('N')).json"
    ConvertTo-Json -InputObject @($Items) -Depth 16 | Set-Content -LiteralPath $itemsPath -Encoding UTF8
    $args = @(
        $script,
        "--operation", $Operation,
        "--targets-file", (Resolve-RepoPath $TargetsPath),
        "--target", $Target,
        "--items-file", $itemsPath
    )
    if ($Explicit) {
        $args += "--explicit"
    }
    if ($ExecuteRequest) {
        $args += "--execute"
    }

    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & python @args 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        Remove-Item -LiteralPath $itemsPath -Force -ErrorAction SilentlyContinue
    }

    $text = (@($output | ForEach-Object { [string]$_ }) -join "`n").Trim()
    if (-not $text) {
        throw "PLC access policy CLI returned no JSON output (exit_code=$exitCode)."
    }
    try {
        return $text | ConvertFrom-Json
    }
    catch {
        throw "PLC access policy CLI returned invalid JSON: $text"
    }
}

function Get-AuthoritativeAccessPolicy {
    $result = Invoke-AuthoritativeAccessPolicy -Operation "describe" -Items @()
    if (-not $result.policy) {
        $message = [string]$result.blocked_reason
        if (-not $message) {
            $message = "PLC access policy could not be loaded."
        }
        throw $message
    }
    return $result.policy
}

function Test-AuthoritativePviReadAccess {
    param(
        [Parameter(Mandatory = $true)]$Variables,
        [bool]$Explicit = $false
    )

    $result = Invoke-AuthoritativeAccessPolicy -Operation "pvi_read" -Items $Variables -Explicit:$Explicit
    return @($result.errors)
}

function Test-AuthoritativeOpcUaReadAccess {
    param(
        [Parameter(Mandatory = $true)]$NodeIds,
        [bool]$Explicit = $false
    )

    $result = Invoke-AuthoritativeAccessPolicy -Operation "opcua_read" -Items $NodeIds -Explicit:$Explicit
    return @($result.errors)
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

function Get-TransferStage {
    param([string[]]$Lines)

    $text = ($Lines -join "`n")
    if ($text -match "(?i)connect|connection") { $stage = "Connected" }
    else { $stage = "PackageValidated" }
    if ($text -match "(?i)service") { $stage = "TargetEnteringService" }
    if ($text -match "(?i)install|download") { $stage = "Installing" }
    if ($text -match "(?i)restart|reboot") { $stage = "Restarting" }
    if ($text -match "(?i)reconnect|waiting") { $stage = "WaitingForReconnection" }
    if ($text -match "(?i)successful") { $stage = "RunVerified" }
    if ($text -match "(?i)error|failed|failure") { $stage = "Failed" }
    return $stage
}

function Get-ReadValue {
    param(
        [Parameter(Mandatory = $true)]$Report,
        [Parameter(Mandatory = $true)][string]$Variable
    )

    $items = @($Report.variables | Where-Object {
        ([string]$_.raw -eq $Variable) -or ([string]$_.name -eq $Variable)
    })
    if ($items.Count -eq 0) {
        return $null
    }
    return $items[0]
}

function Invoke-ApplicationReadiness {
    param(
        [switch]$Quiet,
        $Probe
    )

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $readiness = $targetConfig.application_readiness
    $requiredFields = @(
        "b_alive_variable",
        "interface_version_variable",
        "stage_variable",
        "expected_interface_version",
        "expected_stage"
    )
    $missing = @($requiredFields | Where-Object {
        $value = $readiness.$_
        ($null -eq $value) -or ([string]$value).Trim().Length -eq 0 -or ([string]$value) -match '^<.*>$'
    })
    if ($missing.Count -gt 0) {
        $report = [ordered]@{
            command = "CheckApplicationReadiness"
            ok = $false
            target = $Target
            deployment_state = "runtime_reachable"
            error_code = "APPLICATION_READINESS_UNCONFIGURED"
            retryable = $false
            missing = @($missing)
            checks = @{}
            next_action = "Configure targets.$Target.application_readiness with b_alive_variable, interface_version_variable, stage_variable, expected_interface_version, and expected_stage."
        }
        if ($Quiet) { return [pscustomobject]$report }
        Write-ObjectJson $report
        exit 1
    }

    $variables = @(
        [string]$readiness.b_alive_variable,
        [string]$readiness.interface_version_variable,
        [string]$readiness.stage_variable
    ) | Select-Object -Unique
    $pvi = Invoke-ReadPvi -Quiet -Variables $variables
    $acceptedStatuses = if ($readiness.accepted_plc_status) {
        @($readiness.accepted_plc_status | ForEach-Object { ([string]$_).ToLowerInvariant() })
    }
    else {
        @("run", "warmstart", "coldstart")
    }
    $actualStatus = ([string]$Probe.plc_status).ToLowerInvariant()
    $alive = Get-ReadValue -Report $pvi -Variable ([string]$readiness.b_alive_variable)
    $interface = Get-ReadValue -Report $pvi -Variable ([string]$readiness.interface_version_variable)
    $stageMarker = Get-ReadValue -Report $pvi -Variable ([string]$readiness.stage_variable)
    $aliveValue = if ($alive) { [bool]$alive.value } else { $false }
    $checks = [ordered]@{
        plc_status = [ordered]@{
            ok = $acceptedStatuses -contains $actualStatus
            expected = $acceptedStatuses
            actual = $Probe.plc_status
        }
        b_alive = [ordered]@{
            ok = [bool]($alive -and -not $alive.error -and $aliveValue)
            variable = $readiness.b_alive_variable
            expected = $true
            actual = if ($alive) { $alive.value } else { $null }
        }
        interface_version = [ordered]@{
            ok = [bool]($interface -and -not $interface.error -and ([string]$interface.value -eq [string]$readiness.expected_interface_version))
            variable = $readiness.interface_version_variable
            expected = $readiness.expected_interface_version
            actual = if ($interface) { $interface.value } else { $null }
        }
        stage_marker = [ordered]@{
            ok = [bool]($stageMarker -and -not $stageMarker.error -and ([string]$stageMarker.value -eq [string]$readiness.expected_stage))
            variable = $readiness.stage_variable
            expected = $readiness.expected_stage
            actual = if ($stageMarker) { $stageMarker.value } else { $null }
        }
    }
    $ok = [bool]($pvi.ok -and ($checks.Values | Where-Object { -not $_.ok }).Count -eq 0)
    $report = [ordered]@{
        command = "CheckApplicationReadiness"
        ok = $ok
        target = $Target
        deployment_state = if ($ok) { "application_ready" } else { "failed" }
        stage = if ($ok) { "ApplicationReady" } else { "Failed" }
        error_code = if ($ok) { $null } else { "APPLICATION_NOT_READY" }
        retryable = $false
        checks = $checks
        pvi = $pvi
        next_action = if ($ok) { "Application is ready for testing." } else { "Do not run tests. Fix the failed application readiness checks and re-probe." }
    }
    if ($Quiet) { return [pscustomobject]$report }
    Write-ObjectJson $report
    if (-not $ok) { exit 1 }
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
    $loader = Resolve-ArsimLoaderPath -TargetConfig $targetConfig
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
        deployment_state = "process_started"
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

    $toolchainConfig = Get-SelectedToolchain
    $buildExe = Resolve-RepoPath $toolchainConfig.automation_studio.build_exe
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
        toolchain = $toolchainConfig.id
        toolchain_family = $toolchainConfig.family
        toolchain_version = $toolchainConfig.version
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
    $toolchainConfig = Get-SelectedToolchain
    $targetConfig = Get-TargetConfig $cfg
    $projectMetadata = Get-ProjectConfigurationMetadata
    $isBoundArsimProject = Test-ArsimProjectBinding -TargetConfig $targetConfig -ProjectMetadata $projectMetadata
    $arsimMediaMetadata = Get-BoundArsimMediaMetadata -TargetConfig $targetConfig -ProjectMetadata $projectMetadata
    $wrapper = Resolve-RepoPath "scripts\windows\invoke-pvitransfer-silent.ps1"
    $pviTransfer = Resolve-RepoPath $toolchainConfig.pvi.transfer_exe
    $pil = New-ProbePil $targetConfig.ip
    $log = Join-Path $GeneratedDir "probe_$Target.log"

    $report = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $output = & powershell -NoProfile -ExecutionPolicy Bypass `
            -File $wrapper `
            -PilPath $pil `
            -LogPath $log `
            -PviTransferPath $pviTransfer 2>&1
        $exitCode = $LASTEXITCODE

        $lines = @($output | ForEach-Object { $_.ToString() })
        $cpuType = Get-PviCommandValue $lines "CPUType"
        $arVersion = Get-PviCommandValue $lines "SSWVersion"
        $probeOk = [bool]($exitCode -eq 0 -and $cpuType -and $arVersion)
        $report = [ordered]@{
            command = "Probe"
            ok = $probeOk
            error_code = if ($probeOk) { $null } else { "TARGET_PROBE_INVALID" }
            process_exit_code = $exitCode
            target = $Target
            ip = $targetConfig.ip
            role = $targetConfig.role
            automation_studio_config = if ($Config) { $Config } else { $null }
            cpu_type = $cpuType
            order_number = if ($targetConfig.order_number) { [string]$targetConfig.order_number } else { $null }
            runtime_type = if ($targetConfig.runtime_type) { [string]$targetConfig.runtime_type } elseif ($targetConfig.role -match "arsim") { "AR Simulation" } else { $null }
            configuration_id = if ($targetConfig.configuration_id) { [string]$targetConfig.configuration_id } else { $null }
            configuration_id_source = if ($targetConfig.configuration_id) { "target_config" } else { "unavailable" }
            expected_configuration_id = if ($isBoundArsimProject) { [string]$projectMetadata.configuration_id } else { $null }
            expected_configuration_id_source = if ($isBoundArsimProject) { [string]$projectMetadata.configuration_id_source } else { "unavailable" }
            config_version = if ($targetConfig.config_version) { [string]$targetConfig.config_version } elseif ($arsimMediaMetadata.config_version) { [string]$arsimMediaMetadata.config_version } else { $null }
            config_version_source = if ($targetConfig.config_version) { "target_config" } else { [string]$arsimMediaMetadata.config_version_source }
            partition_layout = if ($targetConfig.partition_layout) { [string]$targetConfig.partition_layout } elseif ($arsimMediaMetadata.partition_layout) { [string]$arsimMediaMetadata.partition_layout } else { $null }
            partition_layout_source = if ($targetConfig.partition_layout) { "target_config" } else { [string]$arsimMediaMetadata.partition_layout_source }
            partition_layout_path = [string]$arsimMediaMetadata.partition_layout_path
            installation_mode = if ($targetConfig.installation_mode) { [string]$targetConfig.installation_mode } else { $null }
            ar_version = $arVersion
            plc_status = Get-PviCommandValue $lines "PLCStatus"
            log_path = $log
            pil_path = $pil
            output_tail = Get-OutputTail $lines
            attempt = $attempt
        }

        if ($report.ok -and $report.cpu_type) {
            break
        }
        if ($attempt -lt 3) {
            Start-Sleep -Seconds 3
        }
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
    $package = Resolve-RucPackagePath
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
    $transferPolicy = Get-TransferPolicy
    $packagePartitionLayout = [string]$info.PartitionLayout
    $packagePartitionLayoutSource = if ($packagePartitionLayout) { "project_information" } else { "unavailable" }
    $packagePartitionLayoutPath = $null
    if (-not $packagePartitionLayout -and $ProjectPath -and $Config) {
        $resolvedProject = Resolve-RepoPath $ProjectPath
        $projectDir = if (Test-Path -LiteralPath $resolvedProject -PathType Container) { $resolvedProject } else { Split-Path -Parent $resolvedProject }
        $cpuDirectory = Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent $package))
        $transferPartitionPath = Join-Path $projectDir (Join-Path "Temp\Transfer" (Join-Path $Config (Join-Path $cpuDirectory "FDATA\SYSTEM\TOC\fscfg.xml")))
        if (Test-Path -LiteralPath $transferPartitionPath -PathType Leaf) {
            $packagePartitionLayout = (Get-FileHash -LiteralPath $transferPartitionPath -Algorithm SHA256).Hash
            $packagePartitionLayoutSource = "transfer_payload_sha256"
            $packagePartitionLayoutPath = $transferPartitionPath
        }
    }
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
        partition_layout = $packagePartitionLayout
        partition_layout_source = $packagePartitionLayoutSource
        partition_layout_path = $packagePartitionLayoutPath
        partition_requirements = [string]$info.PartitionRequirements
        minimum_partition_layout = [string]$info.MinimumPartitionLayout
        installation_mode = if ($info.InstallationMode) { [string]$info.InstallationMode } else { [string]$transferPolicy.install_mode }
        installation_mode_source = if ($info.InstallationMode) { "project_information" } elseif ($transferPolicy.install_mode) { "transfer_pil" } else { "unavailable" }
        required_installation_mode = [string]$info.RequiredInstallationMode
        transfer_policy = $transferPolicy
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
    param(
        [switch]$Quiet,
        [switch]$ForceArsimMismatch
    )

    $cfg = Read-ToolchainConfig
    $targetConfig = Get-TargetConfig $cfg
    $packageInfo = Get-PackageInfo
    $probe = Invoke-Probe -Quiet

    $reasons = New-Object System.Collections.Generic.List[string]
    $warnings = New-Object System.Collections.Generic.List[string]
    $errorCodes = New-Object System.Collections.Generic.List[string]
    $isArsimPackage = ($packageInfo.cpu_type -eq "AR000" -or $packageInfo.runtime_type -match "AR Simulation")
    $isArsimTarget = ($targetConfig.role -match "arsim")
    $targetRole = ([string]$targetConfig.role).ToLowerInvariant()
    $isTrustedDevelopmentTarget = $targetRole -in @("arsim", "dedicated_test_plc")
    $safetyBypassed = [bool](($BypassDownloadSafety -or $ForceArsimDownload) -and $isTrustedDevelopmentTarget)
    $targetPartitionLayout = if ($probe.partition_layout) { [string]$probe.partition_layout } else { [string]$targetConfig.partition_layout }
    $packagePartitionLayout = if ($packageInfo.partition_layout) {
        [string]$packageInfo.partition_layout
    }
    elseif ($packageInfo.partition_requirements) {
        [string]$packageInfo.partition_requirements
    }
    else {
        [string]$packageInfo.minimum_partition_layout
    }
    $targetOrderNumber = if ($probe.order_number) { [string]$probe.order_number } else { [string]$targetConfig.order_number }
    $targetRuntimeType = if ($probe.runtime_type) { [string]$probe.runtime_type } elseif ($targetConfig.runtime_type) { [string]$targetConfig.runtime_type } elseif ($isArsimTarget) { "AR Simulation" } else { $null }
    $targetConfigurationId = if ($probe.configuration_id) { [string]$probe.configuration_id } elseif ($targetConfig.configuration_id) { [string]$targetConfig.configuration_id } elseif ($probe.expected_configuration_id) { [string]$probe.expected_configuration_id } else { $null }
    $targetConfigurationIdSource = if ($probe.configuration_id) { [string]$probe.configuration_id_source } elseif ($targetConfig.configuration_id) { "target_config" } elseif ($probe.expected_configuration_id) { [string]$probe.expected_configuration_id_source } else { "unavailable" }
    $targetConfigVersion = if ($probe.config_version) { [string]$probe.config_version } else { [string]$targetConfig.config_version }
    $targetInstallationMode = if ($probe.installation_mode) { [string]$probe.installation_mode } else { [string]$targetConfig.installation_mode }
    $transferPolicy = $packageInfo.transfer_policy
    $cpuMismatch = [bool]($packageInfo.cpu_type -and $probe.cpu_type -and $packageInfo.cpu_type -ne $probe.cpu_type)
    $orderMismatch = [bool]($packageInfo.order_number -and $targetOrderNumber -and $packageInfo.order_number -ne $targetOrderNumber)

    if (-not $targetConfig.allow_auto_download) {
        if ($targetConfig.role -match "production") {
            $errorCodes.Add("PRODUCTION_DOWNLOAD_BLOCKED")
        }
        else {
            $errorCodes.Add("TARGET_ROLE_MISMATCH")
        }
        $reasons.Add("Target '$Target' does not allow automatic download.")
    }
    if ($targetConfig.role -match "production") {
        $errorCodes.Add("PRODUCTION_DOWNLOAD_BLOCKED")
        $reasons.Add("Target '$Target' is marked as production.")
    }
    if (-not $probe.ok -or -not $probe.cpu_type) {
        $errorCodes.Add("TARGET_PROBE_INVALID")
        $reasons.Add("Target probe did not return a valid CPU type.")
    }
    if ($isArsimPackage -and -not $isArsimTarget) {
        $errorCodes.Add("TARGET_ROLE_MISMATCH")
        $reasons.Add("RUC package is for ARsim, but target '$Target' is not marked as ARsim.")
    }
    if ((-not $isArsimPackage) -and $isArsimTarget) {
        $errorCodes.Add("TARGET_ROLE_MISMATCH")
        $reasons.Add("A physical PLC RUC package cannot be downloaded to ARsim.")
    }
    if ($cpuMismatch -or $orderMismatch) {
        $mismatchReason = "RUC package CPU '$($packageInfo.cpu_type)' / order '$($packageInfo.order_number)' does not match target CPU '$($probe.cpu_type)' / order '$targetOrderNumber'."
        if ($ForceArsimMismatch -and $isArsimTarget) {
            $warnings.Add("FORCED ARsim download: $mismatchReason")
        }
        else {
            $errorCodes.Add("PACKAGE_TARGET_MISMATCH")
            $reasons.Add($mismatchReason)
        }
    }
    elseif (-not $packageInfo.cpu_type -or -not $packageInfo.order_number) {
        $errorCodes.Add("PACKAGE_METADATA_INCOMPLETE")
        $reasons.Add("RUC package must provide CPU and OrderNumber metadata.")
    }
    elseif (-not $probe.cpu_type -or -not $targetOrderNumber) {
        $errorCodes.Add("TARGET_PROBE_INVALID")
        $reasons.Add("Target probe/configuration must provide CPU and OrderNumber metadata.")
    }

    if (-not $packageInfo.runtime_type -or -not $targetRuntimeType) {
        $errorCodes.Add("TARGET_PROBE_INVALID")
        $reasons.Add("Target and RUC package must provide RuntimeType metadata.")
    }
    elseif ([string]$packageInfo.runtime_type -ne [string]$targetRuntimeType) {
        $errorCodes.Add("PACKAGE_TARGET_MISMATCH")
        $reasons.Add("RUC RuntimeType '$($packageInfo.runtime_type)' does not match target RuntimeType '$targetRuntimeType'.")
    }

    if (-not $packageInfo.configuration_id) {
        $errorCodes.Add("PACKAGE_METADATA_INCOMPLETE")
        $reasons.Add("RUC package must provide a configuration identifier.")
    }
    elseif (-not $targetConfigurationId) {
        $errorCodes.Add("TARGET_METADATA_UNKNOWN")
        $reasons.Add("Target configuration ID is unavailable; it was not inferred from the Automation Studio config name '$Config'.")
    }
    elseif ([string]$packageInfo.configuration_id -ne [string]$targetConfigurationId) {
        $errorCodes.Add("PACKAGE_TARGET_MISMATCH")
        $reasons.Add("RUC configuration '$($packageInfo.configuration_id)' does not match target configuration '$targetConfigurationId'.")
    }
    if (-not $packageInfo.config_version -or -not $targetConfigVersion) {
        $errorCodes.Add("TARGET_PROBE_INVALID")
        $reasons.Add("Target and RUC package must provide configuration version metadata.")
    }
    elseif ([string]$packageInfo.config_version -ne [string]$targetConfigVersion) {
        $errorCodes.Add("PACKAGE_TARGET_MISMATCH")
        $reasons.Add("RUC configuration version '$($packageInfo.config_version)' does not match target version '$targetConfigVersion'.")
    }

    if ($packageInfo.ar_version -and $probe.ar_version) {
        if ([string]$packageInfo.ar_version -ne [string]$probe.ar_version) {
            $errorCodes.Add("AR_VERSION_MISMATCH")
            $reasons.Add("RUC AR version '$($packageInfo.ar_version)' does not match target AR version '$($probe.ar_version)'.")
        }
    }
    else {
        $errorCodes.Add("PACKAGE_METADATA_INCOMPLETE")
        $reasons.Add("RUC package and target probe must both provide AR version metadata.")
    }

    if (-not $targetPartitionLayout -or -not $packagePartitionLayout) {
        $errorCodes.Add("PARTITION_LAYOUT_UNKNOWN")
        $reasons.Add("RUC package and target configuration must provide partition layout metadata.")
    }
    elseif ($targetPartitionLayout -ne $packagePartitionLayout) {
        $errorCodes.Add("PARTITION_LAYOUT_INCOMPATIBLE")
        $reasons.Add("RUC partition layout '$packagePartitionLayout' does not match target layout '$targetPartitionLayout'.")
    }

    $packageInstallationMode = if ($packageInfo.installation_mode) { [string]$packageInfo.installation_mode } else { [string]$packageInfo.required_installation_mode }
    $safeTransferPolicy = [bool](
        $isArsimTarget -and
        $transferPolicy.available -and
        $transferPolicy.install_mode -eq "Consistent" -and
        $transferPolicy.install_restriction -eq "AllowUpdatesWithoutDataLoss"
    )
    if (-not $packageInstallationMode) {
        $errorCodes.Add("INSTALLATION_MODE_UNKNOWN")
        $reasons.Add("RUC package or Transfer.pil must provide installation mode metadata.")
    }
    elseif ($safeTransferPolicy) {
        $targetInstallationMode = [string]$transferPolicy.install_mode
        $warnings.Add("Transfer.pil restricts this ARsim update to Consistent / AllowUpdatesWithoutDataLoss; PVITransfer must reject any update that requires data loss.")
    }
    elseif (-not $targetInstallationMode) {
        $errorCodes.Add("INSTALLATION_MODE_UNKNOWN")
        $reasons.Add("Target installation mode is unavailable and Transfer.pil does not declare the safe ARsim update policy.")
    }
    elseif ($packageInstallationMode -ne $targetInstallationMode) {
        $errorCodes.Add("INSTALLATION_MODE_MISMATCH")
        $reasons.Add("RUC installation mode '$packageInstallationMode' does not match target mode '$targetInstallationMode'.")
    }

    if ($ForceArsimDownload) {
        $warnings.Add("force_arsim_download is deprecated; use bypass_download_safety instead.")
    }

    # ARsim and dedicated test PLCs are trusted development targets. Detailed
    # package identity comparisons remain useful diagnostics, but do not block
    # a full RUC transfer. Only the small, explicit hard boundary below does.
    if ($isTrustedDevelopmentTarget) {
        foreach ($reason in @($reasons)) {
            $warnings.Add($(if ($safetyBypassed) { "BYPASSED: $reason" } else { "Compatibility warning: $reason" }))
        }
        $reasons.Clear()
        $errorCodes.Clear()

        if (-not $targetConfig.allow_auto_download) {
            $errorCodes.Add("TARGET_ROLE_MISMATCH")
            $reasons.Add("Target '$Target' does not allow automatic download.")
        }
        if (-not $probe.ok -or -not $probe.cpu_type) {
            $errorCodes.Add("TARGET_PROBE_INVALID")
            $reasons.Add("Target probe did not return a valid CPU type.")
        }
        if ($isArsimPackage -and -not $isArsimTarget) {
            $errorCodes.Add("TARGET_ROLE_MISMATCH")
            $reasons.Add("An ARsim RUC package cannot be downloaded to a dedicated test PLC.")
        }
        if ((-not $isArsimPackage) -and $isArsimTarget) {
            $errorCodes.Add("TARGET_ROLE_MISMATCH")
            $reasons.Add("A physical PLC RUC package cannot be downloaded to ARsim.")
        }
    }
    elseif ($BypassDownloadSafety -or $ForceArsimDownload) {
        $errorCodes.Add("TARGET_ROLE_MISMATCH")
        $reasons.Add("Download safety bypass is limited to ARsim and dedicated test PLC targets.")
    }

    $ok = ($reasons.Count -eq 0)
    $decision = if ($ok) { "allow" } elseif (@($errorCodes | Where-Object { $_ -match "_UNKNOWN$" }).Count -gt 0) { "unknown" } elseif ($errorCodes -contains "PARTITION_LAYOUT_INCOMPATIBLE" -or $errorCodes -contains "INSTALLATION_MODE_MISMATCH") { "manual_intervention" } else { "block" }
    $report = [ordered]@{
        command = "CheckDownload"
        ok = $ok
        target = $Target
        target_ip = $targetConfig.ip
        target_role = $targetConfig.role
        target_allow_auto_download = [bool]$targetConfig.allow_auto_download
        decision = $decision
        package = $packageInfo
        probe = $probe
        compatibility = [ordered]@{
            cpu_type = [ordered]@{ package = $packageInfo.cpu_type; target = $probe.cpu_type; matches = -not $cpuMismatch }
            order_number = [ordered]@{ package = $packageInfo.order_number; target = $targetOrderNumber; matches = -not $orderMismatch }
            runtime_type = [ordered]@{ package = $packageInfo.runtime_type; target = $targetRuntimeType; matches = [bool]($packageInfo.runtime_type -and $targetRuntimeType -and $packageInfo.runtime_type -eq $targetRuntimeType) }
            ar_version = [ordered]@{ package = $packageInfo.ar_version; target = $probe.ar_version; matches = [bool]($packageInfo.ar_version -and $probe.ar_version -and $packageInfo.ar_version -eq $probe.ar_version) }
            configuration_id = [ordered]@{ package = $packageInfo.configuration_id; target = $targetConfigurationId; source = $targetConfigurationIdSource; matches = [bool]($packageInfo.configuration_id -and $targetConfigurationId -and $packageInfo.configuration_id -eq $targetConfigurationId) }
            config_version = [ordered]@{ package = $packageInfo.config_version; target = $targetConfigVersion; source = if ($probe.config_version_source) { $probe.config_version_source } else { "target_config" }; matches = [bool]($packageInfo.config_version -and $targetConfigVersion -and $packageInfo.config_version -eq $targetConfigVersion) }
            installation_mode = [ordered]@{ package = $packageInstallationMode; target = $targetInstallationMode; source = if ($safeTransferPolicy) { "transfer_pil" } else { "target_metadata" }; matches = [bool]($packageInstallationMode -and $targetInstallationMode -and $packageInstallationMode -eq $targetInstallationMode) }
        }
        partition_layout = [ordered]@{
            package = $packagePartitionLayout
            target = $targetPartitionLayout
            package_source = $packageInfo.partition_layout_source
            target_source = if ($probe.partition_layout_source) { $probe.partition_layout_source } else { "target_config" }
            matches = [bool]($packagePartitionLayout -and $targetPartitionLayout -and $packagePartitionLayout -eq $targetPartitionLayout)
        }
        transfer_policy = $transferPolicy
        force_arsim_download = [bool]$ForceArsimDownload
        safety_bypassed = $safetyBypassed
        error_codes = @($errorCodes | Select-Object -Unique)
        reasons = @($reasons)
        warnings = @($warnings)
        next_action = if ($ok) { "A single explicit full-RUC download may be attempted." } else { "Rebuild the complete RUC package, verify target connectivity, and inspect the PVITransfer log." }
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

    $check = Test-DownloadSafety -Quiet -ForceArsimMismatch:$ForceArsimDownload
    if (-not $check.ok) {
        $report = [ordered]@{
            command = "Download"
            ok = $false
            target = $Target
            executed = $false
            attempt_id = $OperationId
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
    $toolchainConfig = Get-SelectedToolchain
    $targetConfig = Get-TargetConfig $cfg
    $wrapper = Resolve-RepoPath "scripts\windows\invoke-pvitransfer-silent.ps1"
    $pviTransfer = Resolve-RepoPath $toolchainConfig.pvi.transfer_exe
    $pil = Resolve-TransferPilPath
    $downloadLogDir = Join-Path $GeneratedDir (Join-Path "downloads" $OperationId)
    New-Item -ItemType Directory -Path $downloadLogDir -Force | Out-Null
    $log = Join-Path $downloadLogDir "pvi_download_$Target.log"
    $conn = "'/IF=tcpip', '/IP=$($targetConfig.ip) /COMT=2500 /AM=* /PT=11169', 'WT=60', 'IGNORE'"

    $output = $null
    $downloadExitCode = 1
    $lines = @()
    $downloadOk = $false
    $output = & powershell -NoProfile -ExecutionPolicy Bypass `
        -File $wrapper `
        -PilPath $pil `
        -LogPath $log `
        -PviTransferPath $pviTransfer `
        -Conn $conn 2>&1
    $downloadExitCode = $LASTEXITCODE
    $lines = Get-OutputLines $output
    $downloadOk = (($downloadExitCode -eq 0) -and (($lines -join "`n") -match "Transfer .* SUCCESSFUL"))
    $verification = $null
    $probeAfter = $null
    $applicationReadiness = $null
    try {
        $probeAfter = Invoke-Probe -Quiet
    }
    catch {
        $probeAfter = [ordered]@{
            ok = $false
            error_code = "TARGET_PROBE_INVALID"
            error = $_.Exception.Message
        }
    }

    if ($downloadOk -and $cfg.opcua.verify_after_download -eq $true) {
        $verification = Invoke-VerifyOpcUa -Quiet
    }
    elseif ($downloadOk -and $cfg.pvi.verify_after_download -eq $true) {
        $verification = Invoke-ReadPvi -Quiet
    }
    if ($downloadOk -and $probeAfter -and $probeAfter.ok) {
        $applicationReadiness = Invoke-ApplicationReadiness -Quiet -Probe $probeAfter
    }

    $ok = $downloadOk
    if ($verification -and $verification.ok -eq $false) {
        $ok = $false
    }
    $transferStage = Get-TransferStage $lines
    $deploymentState = if (-not $downloadOk) {
        "failed"
    }
    elseif (-not $probeAfter -or -not $probeAfter.ok) {
        "unknown"
    }
    elseif ($applicationReadiness -and $applicationReadiness.ok) {
        "application_ready"
    }
    else {
        "runtime_reachable"
    }
    if ($deploymentState -eq "unknown") {
        $ok = $false
    }

    $report = [ordered]@{
        command = "Download"
        ok = $ok
        target = $Target
        target_ip = $targetConfig.ip
        executed = $true
        attempt_id = $OperationId
        deployment_state = $deploymentState
        stage = if ($deploymentState -eq "unknown") { "WaitingForReconnection" } elseif ($applicationReadiness -and $applicationReadiness.ok) { "ApplicationReady" } elseif ($downloadOk) { "RuntimeReachable" } else { $transferStage }
        safety_check = $check
        download_ok = $downloadOk
        download_process_exit_code = $downloadExitCode
        log_path = $log
        pil_path = $pil
        generated_force_pil_path = $null
        probe_after = $probeAfter
        output_tail = Get-OutputTail $lines
        log_tail = if (Test-Path -LiteralPath $log) { @(Get-Content -LiteralPath $log -Tail 40 -ErrorAction SilentlyContinue) } else { @() }
        warnings = @($lines | Where-Object { $_ -match '^WARNING:' })
        error_code = if ($deploymentState -eq "unknown") { "TRANSFER_STATE_UNKNOWN" } elseif (-not $downloadOk) { "TRANSFER_FAILED" } elseif ($applicationReadiness -and -not $applicationReadiness.ok) { $applicationReadiness.error_code } elseif ($verification -and -not $verification.ok) { "APPLICATION_NOT_READY" } else { $null }
        next_action = if ($deploymentState -eq "unknown") { "Re-probe the target and inspect the PVITransfer and Logger output before retrying." } elseif (-not $downloadOk) { "Inspect the transfer log; do not automatically retry with another installation mode." } elseif ($deploymentState -eq "runtime_reachable") { "Verify application readiness before running tests." } else { "Review the deployment report." }
        verification = $verification
        application_readiness = $applicationReadiness
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
    $applicationReadiness = $null

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
        if ($download.executed) {
            $applicationReadiness = $download.application_readiness
        }
        if ($download.executed -and $download.ok) {
            $verification = $download.verification
            if (-not $verification) {
                $verification = Invoke-RunVerificationSuite -Quiet
            }
            if (-not $applicationReadiness) {
                $applicationReadiness = Invoke-ApplicationReadiness -Quiet -Probe $download.probe_after
            }
        }
    }

    $applicationReady = [bool](
        $download -and $download.executed -and $download.deployment_state -eq "application_ready" -and
        $applicationReadiness -and $applicationReadiness.ok -and $verification -and $verification.ok
    )
    $applicationReadiness = [ordered]@{
        state = if ($applicationReady) { "application_ready" } else { "not_ready" }
        process_started = [bool]($start -and $start.ok)
        runtime_reachable = [bool]($download -and $download.probe_after -and $download.probe_after.ok)
        verification_ok = [bool]($verification -and $verification.ok)
        readiness_checks = if ($applicationReadiness) { $applicationReadiness.checks } else { @{} }
        readiness_error_code = if ($applicationReadiness) { $applicationReadiness.error_code } else { "APPLICATION_READINESS_UNCONFIGURED" }
        next_action = if ($applicationReady) { "Application is ready for the configured verification suite." } else { "Confirm PLC status, bAlive, interface version, and stage marker before testing." }
    }
    $ok = [bool]($build.ok -and $start.ok -and $probe.ok -and $package.ok -and $check.ok -and $download.ok -and $applicationReady)
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
        application_readiness = $applicationReadiness
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
        logger = $cfg.logger
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
    $explicitNodes = $false
    if ($OpcUaNodeId -and $OpcUaNodeId.Count -gt 0) {
        $nodes = @($OpcUaNodeId)
        $explicitNodes = $true
    }
    elseif ($cfg.opcua.validation_node_ids) {
        $nodes = @($cfg.opcua.validation_node_ids)
    }

    if ($nodes.Count -eq 0) {
        throw "No OPC UA validation nodes configured. Set opcua.validation_node_ids or pass -OpcUaNodeId."
    }

    $accessErrors = Test-AuthoritativeOpcUaReadAccess -NodeIds $nodes -Explicit:$explicitNodes
    if ($accessErrors.Count -gt 0) {
        $report = [ordered]@{
            command = "VerifyOpcUa"
            ok = $false
            target = $Target
            executed = $false
            access_policy = (Get-AuthoritativeAccessPolicy)
            errors = @($accessErrors)
            requested_nodes = @($nodes)
        }
        if ($Quiet) {
            return $report
        }
        Write-ObjectJson $report
        exit 1
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
    $report | Add-Member -NotePropertyName access_policy -NotePropertyValue (Get-AuthoritativeAccessPolicy) -Force
    $report | Add-Member -NotePropertyName dynamic_request -NotePropertyValue $explicitNodes -Force

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

function Invoke-ReadPvi {
    param(
        [switch]$Quiet,
        [object[]]$Variables
    )

    $cfg = Read-ToolchainConfig
    $toolchainConfig = Get-SelectedToolchain
    $targetConfig = Get-TargetConfig $cfg

    if ($cfg.pvi.enabled -eq $false) {
        throw "PVI reading is disabled in pvi.enabled."
    }

    $variables = @()
    $explicitVariables = $false
    if ($PSBoundParameters.ContainsKey("Variables")) {
        $variables = @($Variables)
        $explicitVariables = $true
    }
    elseif ($PviVariable -and $PviVariable.Count -gt 0) {
        $variables = @(
            foreach ($item in $PviVariable) {
                $item -split "," | Where-Object { $_.Trim().Length -gt 0 } | ForEach-Object { $_.Trim() }
            }
        )
        $explicitVariables = $true
    }
    elseif ($cfg.pvi.read_whitelist) {
        $variables = @($cfg.pvi.read_whitelist)
    }
    elseif ($cfg.pvi.validation_variables) {
        $variables = @($cfg.pvi.validation_variables)
    }

    if ($variables.Count -eq 0) {
        throw "No PVI variables configured. Set pvi.validation_variables or pass -PviVariable."
    }

    $accessErrors = Test-AuthoritativePviReadAccess -Variables $variables -Explicit:$explicitVariables
    if ($accessErrors.Count -gt 0) {
        $report = [ordered]@{
            command = "ReadPvi"
            ok = $false
            errors = @($accessErrors)
        }
        if ($Quiet) {
            return $report
        }
        Write-ObjectJson $report
        exit 1
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
    if ($toolchainConfig.pvi.dll_dir) {
        $args += @("--pvi-dll-dir", (Resolve-RepoPath $toolchainConfig.pvi.dll_dir))
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
    # ReadPvi intentionally returns only compact user-facing values. The
    # generated variable file and access-policy details stay implementation
    # details and are not part of the MCP response.

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

function Invoke-ReadLogger {
    param([switch]$Quiet)

    $toolchainConfig = Get-SelectedToolchain
    $script = Resolve-RepoPath "tools\plc_logger_read.py"
    $args = @(
        $script,
        "--target", $Target,
        "--targets-file", (Resolve-RepoPath $TargetsPath),
        "--logger-type", $LoggerType,
        "--logger-name", $LoggerName,
        "--format", $Format,
        "--pvi-transfer-path", (Resolve-RepoPath $toolchainConfig.pvi.transfer_exe)
    )
    if ($OutputPath) {
        $args += @("--output-path", (Resolve-RepoPath $OutputPath))
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
    $report = Convert-JsonProcessOutput -CommandName "ReadLogger" -Lines $lines -ExitCode $exitCode
    $report | Add-Member -NotePropertyName target -NotePropertyValue $Target -Force

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

function Invoke-WritePvi {
    param([switch]$Quiet)

    if (-not $WritesPath) {
        throw "WritePvi requires -WritesPath pointing to a JSON array of write objects."
    }

    $cfg = Read-ToolchainConfig
    $toolchainConfig = Get-SelectedToolchain
    $targetConfig = Get-TargetConfig $cfg
    if ($targetConfig.role -match "production") {
        throw "Refusing to write PVI variables to production target '$Target'."
    }
    if ($cfg.pvi.enabled -eq $false) {
        throw "PVI is disabled in pvi.enabled."
    }

    $script = Resolve-RepoPath "tools\pvi_write.py"
    $writes = Resolve-RepoPath $WritesPath
    if (-not (Test-Path -LiteralPath $writes)) {
        throw "Writes file was not found: $writes"
    }

    $args = @(
        $script,
        "--target", $Target,
        "--targets-file", (Resolve-RepoPath $TargetsPath),
        "--writes-file", $writes,
        "--cpu-name", $Target
    )
    if ($Execute) {
        $args += "--execute"
    }
    if ($toolchainConfig.pvi.dll_dir) {
        $args += @("--pvi-dll-dir", (Resolve-RepoPath $toolchainConfig.pvi.dll_dir))
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
    $report = Convert-JsonProcessOutput -CommandName "WritePvi" -Lines $lines -ExitCode $exitCode
    $report | Add-Member -NotePropertyName target -NotePropertyValue $Target -Force
    $report | Add-Member -NotePropertyName writes_file -NotePropertyValue $writes -Force

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

function Invoke-IoTestRunner {
    param(
        [Parameter(Mandatory = $true)][string]$RunnerCommand,
        [switch]$Quiet
    )

    $cfg = Read-ToolchainConfig
    $toolchainConfig = Get-SelectedToolchain
    $targetConfig = Get-TargetConfig $cfg
    if ($targetConfig.role -match "production") {
        throw "Refusing to run IO tests on production target '$Target'."
    }
    if ($cfg.pvi.enabled -eq $false) {
        throw "PVI is disabled in pvi.enabled."
    }

    $script = Resolve-RepoPath "tools\plc_io_test_runner.py"
    $suite = Resolve-RepoPath $SuitePath
    $args = @(
        $script,
        "--target", $Target,
        "--targets-file", (Resolve-RepoPath $TargetsPath),
        "--suite", $suite,
        "--cpu-name", $Target,
        "--settle-ms", ([string]$SettleMs)
    )
    if ($Execute) {
        $args += "--execute"
    }
    if ($RunnerCommand -eq "RunIoTestCase") {
        if (-not $CaseName) {
            throw "RunIoTestCase requires -CaseName."
        }
        $args += @("--case-name", $CaseName)
    }
    elseif ($RunnerCommand -eq "ResetTestHarness") {
        $args += "--reset-only"
    }
    if ($toolchainConfig.pvi.dll_dir) {
        $args += @("--pvi-dll-dir", (Resolve-RepoPath $toolchainConfig.pvi.dll_dir))
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
    $report = Convert-JsonProcessOutput -CommandName $RunnerCommand -Lines $lines -ExitCode $exitCode
    $report | Add-Member -NotePropertyName target -NotePropertyValue $Target -Force
    $report | Add-Member -NotePropertyName suite_path -NotePropertyValue $suite -Force

    if ($Quiet) {
        return $report
    }

    Write-ObjectJson $report
    if (-not $report.ok) {
        exit 1
    }
}

try {
$targetChangingCommands = @(
    "StartArsim",
    "Download",
    "WritePvi",
    "RunIoTestCase",
    "RunTestSuite",
    "ResetTestHarness",
    "RunArsimClosedLoop"
)
if (($Command -in $targetChangingCommands) -and (-not $PSBoundParameters.ContainsKey("Target"))) {
    throw "Command '$Command' requires an explicit -Target. No real device is selected implicitly."
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
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ReadLogger -Target test_plc -LoggerType System -LoggerName '`$arlogsys' -Format .html
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command WritePvi -Target test_plc -WritesPath var\pvi_writes.json -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ResetTestHarness -Target test_plc -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command RunIoTestCase -Target test_plc -SuitePath tests\plc\lqr_io_tests.json -CaseName zero_state_zero_output -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command RunTestSuite -Target test_plc -SuitePath tests\plc\lqr_io_tests.json -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command RunVerificationSuite -Target arsim
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command CheckApplicationReadiness -Target arsim
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command RunArsimClosedLoop -Target arsim -Execute
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command ListTargets
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\plc_toolchain.ps1 -Command GetTargetConfig -Target test_plc
"@ | Write-Output
    }
    "Build" { Invoke-Build }
    "StartArsim" { Invoke-StartArsim }
    "Probe" { Invoke-Probe }
    "DescribePackage" { Invoke-DescribePackage }
    "CheckDownload" { Test-DownloadSafety -ForceArsimMismatch:$ForceArsimDownload }
    "Download" { Invoke-Download }
    "VerifyOpcUa" { Invoke-VerifyOpcUa }
    "ReadPvi" { Invoke-ReadPvi }
    "ReadLogger" { Invoke-ReadLogger }
    "WritePvi" { Invoke-WritePvi }
    "RunIoTestCase" { Invoke-IoTestRunner -RunnerCommand "RunIoTestCase" }
    "RunTestSuite" { Invoke-IoTestRunner -RunnerCommand "RunTestSuite" }
    "ResetTestHarness" { Invoke-IoTestRunner -RunnerCommand "ResetTestHarness" }
    "RunArsimClosedLoop" { Invoke-RunArsimClosedLoop }
    "RunVerificationSuite" { Invoke-RunVerificationSuite }
    "CheckApplicationReadiness" { Invoke-ApplicationReadiness -Probe (Invoke-Probe -Quiet) }
    "GetTargetConfig" { Invoke-GetTargetConfig }
    "ListTargets" { Invoke-ListTargets }
}
}
catch {
    $message = $_.Exception.Message
    $errorCode = if ($message -match "^([A-Z][A-Z0-9_]+):") {
        $Matches[1]
    }
    elseif ($message -match "Project was not found|Project path") {
        "PROJECT_CONFIG_REQUIRED"
    }
    elseif ($message -match "config|Hardware\.hw") {
        "TOOLCHAIN_CONFIG_REQUIRED"
    }
    elseif ($message -match "ARsim loader") {
        "ARSIM_LOADER_REQUIRED"
    }
    else {
        "TOOLCHAIN_ERROR"
    }
    $report = [ordered]@{
        command = $Command
        ok = $false
        error = $message
        error_code = $errorCode
        retryable = $false
        stage = "execution"
        attempt_id = $OperationId
        category = $_.CategoryInfo.Category.ToString()
        target = $Target
    }
    Write-ObjectJson $report
    exit 1
}
