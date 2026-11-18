function Test-Configuration($Config) {
    if (!$Config.pipeName -or $Config.pipeName -notmatch '^[A-Za-z0-9_.-]{1,200}$' -or
        $Config.sampleSeconds -le 0 -or $Config.staleSeconds -le $Config.sampleSeconds -or
        @($Config.slots).Count -eq 0 -or $Config.pviPort -notin $Config.tcpPorts) { throw 'Invalid configuration' }
    $addresses = @()
    foreach ($slot in $Config.slots) {
        $address = $null
        if (![Net.IPAddress]::TryParse($slot, [ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or ![Net.IPAddress]::IsLoopback($address)) { throw "Invalid loopback slot: $slot" }
        $addresses += $address.ToString()
    }
    if (@($addresses | Select-Object -Unique).Count -ne $addresses.Count) { throw 'Duplicate slot address' }
    foreach ($port in @($Config.tcpPorts) + @($Config.udpPorts)) {
        if ($port -isnot [int] -and $port -isnot [long]) { throw "Invalid port: $port" }
        if ($port -lt 1 -or $port -gt 65535) { throw "Invalid port: $port" }
    }
}

function Test-CoversSlot($LocalAddress, $SlotAddress) {
    $address = $null
    # An unrecognized address cannot safely be treated as non-conflicting.
    if (![Net.IPAddress]::TryParse($LocalAddress, [ref]$address)) { return $true }
    if ($address.Equals([Net.IPAddress]::Any) -or $address.Equals([Net.IPAddress]::IPv6Any)) { return $true }
    if ($address.IsIPv4MappedToIPv6) { $address = $address.MapToIPv4() }
    return $address.Equals([Net.IPAddress]::Any) -or $address.Equals([Net.IPAddress]::Parse($SlotAddress))
}

function Get-Occupancy($Config) {
    $tcp = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
    $udp = @(Get-NetUDPEndpoint -ErrorAction Stop)
    $processes = @{}
    $rows = @(
        foreach ($endpoint in $tcp) {
            if ($endpoint.LocalPort -in $Config.tcpPorts) {
                [pscustomobject]@{ protocol='TCP'; address=$endpoint.LocalAddress; port=[int]$endpoint.LocalPort; pid=[int]$endpoint.OwningProcess }
            }
        }
        foreach ($endpoint in $udp) {
            if ($endpoint.LocalPort -in $Config.udpPorts) {
                [pscustomobject]@{ protocol='UDP'; address=$endpoint.LocalAddress; port=[int]$endpoint.LocalPort; pid=[int]$endpoint.OwningProcess }
            }
        }
    )
    foreach ($row in $rows) {
        if (!$processes.ContainsKey($row.pid)) {
            $p = Get-Process -Id $row.pid -ErrorAction SilentlyContinue
            $processes[$row.pid] = @{ name=if ($p) { $p.ProcessName } else { $null }; path=if ($p) { try { $p.Path } catch { $null } } else { $null } }
        }
        $row | Add-Member -NotePropertyMembers $processes[$row.pid]
    }
    $time = [datetime]::UtcNow.ToString('o')
    $i = 0
    $slots = @(foreach ($ip in $Config.slots) {
        $i++
        $conflicts = @($rows | Where-Object { Test-CoversSlot $_.address $ip })
        [pscustomobject]@{ slot=$i; ip=$ip; pviPort=$Config.pviPort; state=if ($conflicts.Count) { 'blocked' } else { 'free' }; runId=$null; sampledAt=$time; conflicts=$conflicts }
    })
    [pscustomobject]@{ ok=$true; sampledAt=$time; stale=$false; error=$null; slots=$slots }
}

function Get-Snapshot($Snapshot, $Config, $SampleError) {
    $stale = !$Snapshot -or $SampleError -or ([datetime]::UtcNow - [datetime]::Parse($Snapshot.sampledAt).ToUniversalTime()).TotalSeconds -gt $Config.staleSeconds
    if (!$Snapshot) {
        $i = 0
        return [pscustomobject]@{ ok=$false; sampledAt=$null; stale=$true; error=$SampleError; slots=@(foreach ($ip in $Config.slots) { $i++; [pscustomobject]@{ slot=$i; ip=$ip; pviPort=$Config.pviPort; state='needs_attention'; runId=$null; sampledAt=$null; conflicts=@() } }) }
    }
    # Copy before marking stale; the last successful sample remains available.
    $result = $Snapshot | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    if ($stale) {
        $result.ok = $false; $result.stale = $true; $result.error = if ($SampleError) { $SampleError } else { 'Occupancy sample expired' }
        foreach ($slot in $result.slots) { $slot.state = 'needs_attention' }
    }
    return $result
}
