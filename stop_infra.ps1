$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFilePath = Join-Path $ProjectRoot '.env'
$RuntimeRootEnvValue = "$($env:LOCAL_RUNTIME_ROOT)".Trim()
if (-not $RuntimeRootEnvValue -and (Test-Path $EnvFilePath)) {
    foreach ($line in (Get-Content $EnvFilePath -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*#') { continue }
        if ($line -match '^\s*$') { continue }
        if ($line -match '^\s*LOCAL_RUNTIME_ROOT=(.*)$') {
            $RuntimeRootEnvValue = $Matches[1].Trim()
            break
        }
    }
}
if (-not $RuntimeRootEnvValue) {
    $RuntimeRootEnvValue = 'src/.runtime'
}

$PostgresStartMode = "$($env:AZURIS_POSTGRES_START_MODE)".Trim().ToLower()
if (-not $PostgresStartMode -and (Test-Path $EnvFilePath)) {
    foreach ($line in (Get-Content $EnvFilePath -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*#') { continue }
        if ($line -match '^\s*$') { continue }
        if ($line -match '^\s*AZURIS_POSTGRES_START_MODE=(.*)$') {
            $PostgresStartMode = $Matches[1].Trim().ToLower()
            break
        }
    }
}
if (-not $PostgresStartMode) {
    $PostgresStartMode = 'direct'
}
if ($PostgresStartMode -notin @('direct', 'auto', 'pg_ctl')) {
    $PostgresStartMode = 'direct'
}

$RuntimeRoot = if ([System.IO.Path]::IsPathRooted($RuntimeRootEnvValue)) {
    [System.IO.Path]::GetFullPath($RuntimeRootEnvValue)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RuntimeRootEnvValue))
}
$env:LOCAL_RUNTIME_ROOT = $RuntimeRootEnvValue

$PostgresDir = Join-Path $RuntimeRoot 'postgres'
$RuntimeRunDir = Join-Path $RuntimeRoot 'run'
$PostgresCredentialsFile = Join-Path $PostgresDir 'credentials.env'

$PostgresPidFile = Join-Path $RuntimeRunDir 'postgres.pid'
$RedisDir = Join-Path $RuntimeRoot 'redis'
$RedisPidFile = Join-Path $RuntimeRunDir 'redis.pid'
$RedisPort = if ($env:REDIS_PORT) { $env:REDIS_PORT } else { '6379' }
$PostgresDataDir = Join-Path $PostgresDir 'data'

$PostgresPort = if ($env:POSTGRES_PORT) {
    $env:POSTGRES_PORT
}
else {
    $credentialsPort = $null
    if (Test-Path $PostgresCredentialsFile) {
        foreach ($line in (Get-Content $PostgresCredentialsFile -ErrorAction SilentlyContinue)) {
            if ($line -match '^AZURIS_DB_PORT=(\d+)\s*$') {
                $credentialsPort = $Matches[1]
                break
            }
        }
    }

    if ($credentialsPort) { $credentialsPort } else { '55432' }
}


function Test-TcpPortOpen {
    param(
        [Parameter(Mandatory = $true)][string]$TargetHost,
        [Parameter(Mandatory = $true)][int]$TargetPort,
        [int]$TimeoutMs = 900
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $connected -or -not $client.Connected) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Wait-TcpPortClosed {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetHost,
        [Parameter(Mandatory = $true)][int]$TargetPort,
        [int]$MaxSeconds = 25
    )

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (-not (Test-TcpPortOpen -TargetHost $TargetHost -TargetPort $TargetPort)) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return (-not (Test-TcpPortOpen -TargetHost $TargetHost -TargetPort $TargetPort))
}

function Get-PortOwnerSummary {
    param(
        [Parameter(Mandatory = $true)][int]$Port
    )

    try {
        $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $listener) {
            return "port $Port owner unresolved"
        }

        $pid = [int]$listener.OwningProcess
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pid" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine) {
            return "PID=$pid CMD=$($proc.CommandLine)"
        }

        return "PID=$pid CMD=<unavailable>"
    }
    catch {
        return "port $Port owner lookup failed: $($_.Exception.Message)"
    }
}

function Wait-ProcessExit {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [int]$MaxSeconds = 8
    )

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue))
}

function Stop-ProcessGracefulThenForce {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) {
        return
    }

    Write-Host "[INFO] Stopping $ServiceName PID=$ProcessId"
    try {
        # Background processes (Java, Postgres) do not respond to graceful window close signals.
        # We use -Force directly to terminate them immediately and avoid hanging.
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
    catch {
        Write-Host "[WARN] Failed to stop process ${ProcessId}. Error: $_"
    }

    if (Wait-ProcessExit -ProcessId $ProcessId -MaxSeconds 5) {
        return
    }

    throw "Failed to stop $ServiceName PID=$ProcessId after forced termination"
}

function Stop-ProcessByPidFile {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$PidFilePath
    )

    if (-not (Test-Path $PidFilePath)) {
        return
    }

    $pidRaw = (Get-Content $PidFilePath -ErrorAction SilentlyContinue | Select-Object -First 1)
    $pidText = "$pidRaw".Trim()

    if ($pidText -match '^\d+$') {
        Stop-ProcessGracefulThenForce -ProcessId ([int]$pidText) -ServiceName $ServiceName
    }

    Remove-Item -LiteralPath $PidFilePath -Force -ErrorAction SilentlyContinue
}

function Stop-RuntimePostgresProcesses {
    $runtimePostgresToken = $PostgresDir.ToLower().Replace('\', '/')
    $postgresProcs = Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $postgresProcs) {
        $cmd = "$($proc.CommandLine)"
        if (-not $cmd) { continue }

        $cmdNorm = $cmd.ToLower().Replace('\', '/')
        if (-not $cmdNorm.Contains($runtimePostgresToken)) { continue }

        Stop-ProcessGracefulThenForce -ProcessId ([int]$proc.ProcessId) -ServiceName 'PostgreSQL'
    }
}

function Stop-Postgres {
    $pgCtl = Join-Path $PostgresDir 'bin/pg_ctl.exe'
    if ($PostgresStartMode -ne 'direct' -and (Test-Path $pgCtl) -and (Test-Path $PostgresDataDir)) {
        & $pgCtl -D $PostgresDataDir status *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host '[INFO] Stopping PostgreSQL gracefully via pg_ctl...'
            & $pgCtl -D $PostgresDataDir stop -m fast -w -t 30 *> $null
            if ($LASTEXITCODE -ne 0) {
                Write-Host '[WARN] pg_ctl stop returned non-zero, continuing with process-level stop.'
            }
        }
        else {
            Write-Host '[INFO] PostgreSQL runtime status = not running.'
        }
    }
    elseif ((-not (Test-Path $pgCtl)) -or (-not (Test-Path $PostgresDataDir))) {
        Write-Host '[INFO] PostgreSQL runtime not found. Skipping pg_ctl stop.'
    }
    else {
        Write-Host '[INFO] PostgreSQL start mode is direct. Skipping pg_ctl stop.'
    }

    Stop-ProcessByPidFile -ServiceName 'PostgreSQL' -PidFilePath $PostgresPidFile
    Stop-RuntimePostgresProcesses
}

function Stop-Redis {
    Stop-ProcessByPidFile -ServiceName 'Redis' -PidFilePath $RedisPidFile

    $runtimeRedisToken = $RedisDir.ToLower().Replace('\', '/')
    $redisProcs = Get-CimInstance Win32_Process -Filter "Name='redis-server.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $redisProcs) {
        $cmd = "$($proc.CommandLine)"
        if (-not $cmd) { continue }

        $cmdNorm = $cmd.ToLower().Replace('\', '/')
        if (-not $cmdNorm.Contains($runtimeRedisToken)) { continue }

        Stop-ProcessGracefulThenForce -ProcessId ([int]$proc.ProcessId) -ServiceName 'Redis'
    }
}

function Assert-InfraStopped {
    $checks = @(
        @{ Name = 'PostgreSQL'; Port = [int]$PostgresPort; Enabled = $true },
        @{ Name = 'Redis'; Port = [int]$RedisPort; Enabled = $true }
    )

    $failures = @()
    foreach ($check in $checks) {
        if (-not $check.Enabled) { continue }

        $closed = Wait-TcpPortClosed -Name $check.Name -TargetHost '127.0.0.1' -TargetPort $check.Port -MaxSeconds 25
        if (-not $closed) {
            $owner = Get-PortOwnerSummary -Port $check.Port
            $failures += "$($check.Name) port $($check.Port) is still open after stop. $owner"
        }
    }

    if ($failures.Count -gt 0) {
        throw ($failures -join "`n")
    }
}

Write-Host '==============================================='
Write-Host '  Azuris Local Infra Teardown (Windows)'
Write-Host '==============================================='
Write-Host "Project root: $ProjectRoot"

Stop-Postgres
Stop-Redis
Stop-RuntimePostgresProcesses

Assert-InfraStopped

Write-Host '[OK] Local Redis/PostgreSQL teardown complete.'
