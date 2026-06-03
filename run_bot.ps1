$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = 'azuris-bot'
$LogDir = Join-Path $ProjectRoot 'logs'
$EcosystemFile = Join-Path $ProjectRoot 'ecosystem.config.js'

function Get-EnvFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFile,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path $EnvFile)) {
        return ''
    }

    foreach ($line in (Get-Content $EnvFile -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*#') { continue }
        if ($line -match '^\s*$') { continue }
        if ($line -match "^\s*$([Regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim()
        }
    }

    return ''
}

$EnvFilePath = Join-Path $ProjectRoot '.env'
$RuntimeRootEnvValue = "$($env:LOCAL_RUNTIME_ROOT)".Trim()
if (-not $RuntimeRootEnvValue) {
    $RuntimeRootEnvValue = Get-EnvFileValue -EnvFile $EnvFilePath -Key 'LOCAL_RUNTIME_ROOT'
}
if (-not $RuntimeRootEnvValue) {
    $RuntimeRootEnvValue = 'src/.runtime'
}

$RuntimeRoot = if ([System.IO.Path]::IsPathRooted($RuntimeRootEnvValue)) {
    [System.IO.Path]::GetFullPath($RuntimeRootEnvValue)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RuntimeRootEnvValue))
}
$env:LOCAL_RUNTIME_ROOT = $RuntimeRootEnvValue

$JavaDir = Join-Path $RuntimeRoot 'java'
$KafkaDir = Join-Path $RuntimeRoot 'kafka'
$PostgresDir = Join-Path $RuntimeRoot 'postgres'
$PostgresCredentialsFile = Join-Path $PostgresDir 'credentials.env'
$InstallScript = Join-Path $ProjectRoot 'install_services.ps1'
$StopInfraScript = Join-Path $ProjectRoot 'stop_infra.ps1'

$PostgresStartMode = "$($env:AZURIS_POSTGRES_START_MODE)".Trim().ToLower()
if (-not $PostgresStartMode) {
    $PostgresStartMode = 'direct'
}
if ($PostgresStartMode -notin @('direct', 'auto', 'pg_ctl')) {
    $PostgresStartMode = 'direct'
}
$env:AZURIS_POSTGRES_START_MODE = $PostgresStartMode

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
$KafkaPort = if ($env:KAFKA_PORT) { $env:KAFKA_PORT } else { '59092' }
$ZookeeperPort = if ($env:ZOOKEEPER_PORT) { $env:ZOOKEEPER_PORT } else { '2181' }

$Pm2Mode = $false
$Pm2Fresh = $false
$PreflightOnly = $false

foreach ($arg in $args) {
    switch ($arg) {
        '--pm2' { $Pm2Mode = $true }
        '--pm2-fresh' { $Pm2Mode = $true; $Pm2Fresh = $true }
        '--preflight-only' { $PreflightOnly = $true }
    }
}

Set-Location $ProjectRoot

Write-Host '==============================================='
Write-Host '  Azuris Discord Bot - Windows Launcher'
Write-Host '==============================================='
Write-Host "Project root: $ProjectRoot"
Write-Host "Runtime root: $RuntimeRoot"
Write-Host "PostgreSQL start mode: $PostgresStartMode"

$venvPath = Join-Path $ProjectRoot '.venv'
$venvPy = Join-Path $venvPath 'Scripts/python.exe'
if (-not (Test-Path $venvPy)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCmd) {
        throw "Missing .venv interpreter at $venvPy and no global 'python' found to create it."
    }

    Write-Host '[INFO] .venv interpreter missing. Creating virtual environment at .venv...'
    python -m venv $venvPath
}

if (-not (Test-Path $venvPy)) {
    throw "Failed to create .venv interpreter: $venvPy"
}

Write-Host "[OK] Using interpreter: $venvPy"
$env:AZURIS_PYTHON = $venvPy

function Initialize-Runtime {
    $needsBootstrap = $false
    if (-not (Test-Path (Join-Path $JavaDir 'bin/java.exe'))) { $needsBootstrap = $true }
    if (-not (Test-Path (Join-Path $KafkaDir 'bin/windows/kafka-server-start.bat'))) { $needsBootstrap = $true }
    if (-not (Test-Path (Join-Path $PostgresDir 'bin/initdb.exe'))) { $needsBootstrap = $true }
    if (-not (Test-Path $PostgresCredentialsFile)) { $needsBootstrap = $true }

    if (-not $needsBootstrap) {
        Write-Host '[OK] Local runtime already exists'
        return
    }

    Write-Host '[INFO] Local runtime missing. Bootstrapping via install_services.ps1'
    & powershell -ExecutionPolicy Bypass -File $InstallScript
}

function Update-RuntimePortsFromCredentials {
    if ($env:POSTGRES_PORT) {
        return
    }

    if (-not (Test-Path $PostgresCredentialsFile)) {
        return
    }

    foreach ($line in (Get-Content $PostgresCredentialsFile -ErrorAction SilentlyContinue)) {
        if ($line -match '^AZURIS_DB_PORT=(\d+)\s*$') {
            $script:PostgresPort = $Matches[1]
            return
        }
    }
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFile,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if (-not (Test-Path $EnvFile)) {
        New-Item -ItemType File -Path $EnvFile | Out-Null
    }

    $lines = Get-Content -Path $EnvFile -ErrorAction SilentlyContinue
    if ($null -eq $lines) {
        $lines = @()
    }

    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$([Regex]::Escape($Key))=") {
            $lines[$i] = "$Key=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        $lines += "$Key=$Value"
    }

    Set-Content -Path $EnvFile -Value $lines -Encoding UTF8
}

function Remove-EnvBackups {
    Get-ChildItem -Path $ProjectRoot -File -Filter '.env.bak*' -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Sync-RuntimeEnv {
    $dbUrl = ''
    if (Test-Path $PostgresCredentialsFile) {
        $lines = Get-Content $PostgresCredentialsFile
        $map = @{}
        foreach ($line in $lines) {
            if ($line -match '^\s*#') { continue }
            if ($line -match '^\s*$') { continue }
            $parts = $line -split '=', 2
            if ($parts.Count -eq 2) {
                $map[$parts[0].Trim()] = $parts[1]
            }
        }
        if ($map.ContainsKey('AZURIS_DB_USER') -and $map.ContainsKey('AZURIS_DB_PASSWORD') -and $map.ContainsKey('AZURIS_DB_NAME') -and $map.ContainsKey('AZURIS_DB_PORT')) {
            $dbUrl = "postgresql://$($map['AZURIS_DB_USER']):$($map['AZURIS_DB_PASSWORD'])@127.0.0.1:$($map['AZURIS_DB_PORT'])/$($map['AZURIS_DB_NAME'])?sslmode=disable"
        }
    }

    $envFile = Join-Path $ProjectRoot '.env'
    Remove-EnvBackups
    Set-EnvValue -EnvFile $envFile -Key 'LOCAL_RUNTIME_ROOT' -Value $RuntimeRootEnvValue
    Set-EnvValue -EnvFile $envFile -Key 'JAVA_HOME' -Value $JavaDir
    Set-EnvValue -EnvFile $envFile -Key 'KAFKA_BOOTSTRAP_SERVERS' -Value "127.0.0.1:$KafkaPort"
    Set-EnvValue -EnvFile $envFile -Key 'AZURIS_POSTGRES_START_MODE' -Value $PostgresStartMode

    if ($dbUrl) {
        Set-EnvValue -EnvFile $envFile -Key 'DATABASE_URL' -Value $dbUrl
    }
    Remove-EnvBackups
}

function Test-TcpPortReady {
    param(
        [Parameter(Mandatory = $true)][string]$TargetHost,
        [Parameter(Mandatory = $true)][int]$TargetPort,
        [int]$TimeoutMs = 1000
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

function Wait-TcpPortReady {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetHost,
        [Parameter(Mandatory = $true)][int]$TargetPort,
        [int]$MaxSeconds = 45
    )

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (Test-TcpPortReady -TargetHost $TargetHost -TargetPort $TargetPort) {
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "$Name is not ready on $TargetHost`:$TargetPort after $MaxSeconds seconds"
}

function Wait-TcpPortClosed {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$TargetHost,
        [Parameter(Mandatory = $true)][int]$TargetPort,
        [int]$MaxSeconds = 25
    )

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (-not (Test-TcpPortReady -TargetHost $TargetHost -TargetPort $TargetPort)) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return (-not (Test-TcpPortReady -TargetHost $TargetHost -TargetPort $TargetPort))
}

function Wait-PostgresQueryReady {
    param(
        [int]$MaxSeconds = 45
    )

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (Test-PostgresQueryReady) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return (Test-PostgresQueryReady)
}

function Test-PidFileProcessRunning {
    param(
        [Parameter(Mandatory = $true)][string]$PidFilePath
    )

    if (-not (Test-Path $PidFilePath)) {
        return $false
    }

    $pidRaw = Get-Content -Path $PidFilePath -ErrorAction SilentlyContinue | Select-Object -First 1
    $pidText = "$pidRaw".Trim()
    if (-not ($pidText -match '^\d+$')) {
        return $false
    }

    return ($null -ne (Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue))
}

function Test-PostgresQueryReady {
    $psql = Join-Path $PostgresDir 'bin/psql.exe'
    if (-not (Test-Path $psql)) {
        return $false
    }

    $username = 'azuris'
    $password = ''
    $dbname = 'azuris'

    if (Test-Path $PostgresCredentialsFile) {
        foreach ($line in (Get-Content $PostgresCredentialsFile)) {
            if ($line -match '^AZURIS_DB_USER=(.+)$') { $username = $Matches[1].Trim() }
            elseif ($line -match '^AZURIS_DB_PASSWORD=(.*)$') { $password = $Matches[1] }
            elseif ($line -match '^AZURIS_DB_NAME=(.+)$') { $dbname = $Matches[1].Trim() }
        }
    }

    $oldPgPassword = $env:PGPASSWORD
    $oldPgConnectTimeout = $env:PGCONNECT_TIMEOUT
    try {
        $env:PGCONNECT_TIMEOUT = '5'
        if ($password) {
            $env:PGPASSWORD = $password
        }
        # -w disables interactive password prompts so launcher can fail fast.
        $result = & $psql -w -h 127.0.0.1 -p $PostgresPort -U $username -d $dbname -tAc "SELECT 1" 2>$null
        return ($LASTEXITCODE -eq 0 -and ("$result".Trim() -eq '1'))
    }
    catch {
        return $false
    }
    finally {
        if ($null -eq $oldPgConnectTimeout) {
            Remove-Item Env:PGCONNECT_TIMEOUT -ErrorAction SilentlyContinue
        }
        else {
            $env:PGCONNECT_TIMEOUT = $oldPgConnectTimeout
        }

        if ($null -eq $oldPgPassword) {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        else {
            $env:PGPASSWORD = $oldPgPassword
        }
    }
}

function Start-PostgresDirect {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresExePath,
        [Parameter(Mandatory = $true)][string]$PostgresDataDirPath,
        [Parameter(Mandatory = $true)][string]$RuntimeRootPath
    )

    if (-not (Test-Path $PostgresExePath)) {
        throw "Missing postgres executable for direct start: $PostgresExePath"
    }

    $directOutLogFile = Join-Path $RuntimeRootPath 'logs/postgres.direct.out.log'
    $directErrLogFile = Join-Path $RuntimeRootPath 'logs/postgres.direct.err.log'
    Remove-Item -LiteralPath $directOutLogFile, $directErrLogFile -Force -ErrorAction SilentlyContinue

    $directProc = Start-Process -FilePath $PostgresExePath -ArgumentList @('-D', $PostgresDataDirPath, '-p', "$PostgresPort") -PassThru -WindowStyle Hidden -RedirectStandardOutput $directOutLogFile -RedirectStandardError $directErrLogFile

    $postgresPidFile = Join-Path $RuntimeRootPath 'run/postgres.pid'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $postgresPidFile) | Out-Null
    Set-Content -Path $postgresPidFile -Value $directProc.Id -Encoding UTF8

    Wait-TcpPortReady -Name 'PostgreSQL' -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort) -MaxSeconds 30
    if (-not (Wait-PostgresQueryReady -MaxSeconds 45)) {
        $logTail = ''
        if (Test-Path $directErrLogFile) {
            $logTail = (Get-Content -Path $directErrLogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        if ((-not $logTail) -and (Test-Path (Join-Path $RuntimeRootPath 'logs/postgres.log'))) {
            $logTail = (Get-Content -Path (Join-Path $RuntimeRootPath 'logs/postgres.log') -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        if ($logTail) {
            throw "PostgreSQL direct start failed. Recent logs:`n$logTail"
        }
        throw 'PostgreSQL direct start failed. Check runtime postgres logs.'
    }
}

function Start-PostgresIfNeeded {
    $pgCtl = Join-Path $PostgresDir 'bin/pg_ctl.exe'
    $postgresExe = Join-Path $PostgresDir 'bin/postgres.exe'
    $postgresDataDir = Join-Path $PostgresDir 'data'
    $postgresLogFile = Join-Path $RuntimeRoot 'logs/postgres.log'

    $pgCtlAvailable = Test-Path $pgCtl
    $effectiveStartMode = $PostgresStartMode

    if (-not (Test-Path $postgresDataDir)) {
        throw "Missing PostgreSQL data directory: $postgresDataDir"
    }

    if (-not $pgCtlAvailable) {
        if ($effectiveStartMode -eq 'auto') {
            Write-Host '[WARN] pg_ctl is missing. Falling back to direct postgres.exe startup.'
            $effectiveStartMode = 'direct'
        }
        elseif ($effectiveStartMode -eq 'pg_ctl') {
            throw "Missing PostgreSQL control binary: $pgCtl"
        }
    }

    if ($pgCtlAvailable -and $effectiveStartMode -ne 'direct') {
        & $pgCtl -D $postgresDataDir status *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host '[OK] PostgreSQL runtime instance is already running'
            Wait-TcpPortReady -Name 'PostgreSQL' -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort) -MaxSeconds 30
            if (-not (Wait-PostgresQueryReady -MaxSeconds 20)) {
                throw 'PostgreSQL TCP port is open but SQL query check failed. Check runtime postgres logs and credentials.'
            }
            return
        }
    }

    if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort)) {
        $ownerPid = $null
        $ownerCmd = ''
        $runtimePid = $null
        $isRuntimeProcess = $false

        try {
            $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort ([int]$PostgresPort) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($listener) {
                $ownerPid = [int]$listener.OwningProcess
            }
        }
        catch {
        }

        $postmasterPidFile = Join-Path $postgresDataDir 'postmaster.pid'
        if (Test-Path $postmasterPidFile) {
            try {
                $firstPidLine = Get-Content -Path $postmasterPidFile -TotalCount 1 -ErrorAction SilentlyContinue
                if ($firstPidLine -match '^\d+$') {
                    $runtimePid = [int]$firstPidLine
                }
            }
            catch {
            }
        }

        if ($ownerPid -and $runtimePid -and $ownerPid -eq $runtimePid) {
            $isRuntimeProcess = $true
        }

        try {
            if ($ownerPid) {
                $ownerProc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
                if ($ownerProc -and $ownerProc.CommandLine) {
                    $ownerCmd = "$($ownerProc.CommandLine)"
                    $cmdLower = $ownerCmd.ToLower()
                    if ($cmdLower.Contains($postgresDataDir.ToLower()) -or $cmdLower.Contains($PostgresDir.ToLower())) {
                        $isRuntimeProcess = $true
                    }
                }
            }
        }
        catch {
        }

        if (-not $ownerPid -and $runtimePid) {
            $ownerPid = $runtimePid
            $isRuntimeProcess = $true
        }

        if ($ownerPid -and -not $ownerCmd) {
            try {
                $ownerProcFallback = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
                if ($ownerProcFallback -and $ownerProcFallback.ProcessName -match 'postgres') {
                    $isRuntimeProcess = $true
                }
            }
            catch {
            }
        }

        if (-not $isRuntimeProcess -and $ownerPid) {
            try {
                $postgresDirToken = $PostgresDir.ToLower().Replace('\', '/')
                $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ownerPid" -ErrorAction SilentlyContinue
                foreach ($child in $children) {
                    $childCmd = "$($child.CommandLine)"
                    if (-not $childCmd) { continue }

                    $childCmdLower = $childCmd.ToLower().Replace('\', '/')
                    if ($childCmdLower.Contains('postgres.exe') -and $childCmdLower.Contains($postgresDirToken)) {
                        $isRuntimeProcess = $true
                        break
                    }
                }
            }
            catch {
            }
        }

        if ($isRuntimeProcess) {
            Write-Host "[OK] PostgreSQL runtime instance is already listening on port $PostgresPort"
            Wait-TcpPortReady -Name 'PostgreSQL' -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort) -MaxSeconds 30
            if (-not (Wait-PostgresQueryReady -MaxSeconds 20)) {
                throw 'PostgreSQL TCP port is open but SQL query check failed. Check runtime postgres logs and credentials.'
            }
            return
        }

        throw "Port $PostgresPort is already in use by a non-project PostgreSQL process. Stop that process and rerun. PID=$ownerPid CMD=$ownerCmd"
    }

    Write-Host '[INFO] Starting PostgreSQL runtime in background...'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $postgresLogFile) | Out-Null

    if ($effectiveStartMode -eq 'direct') {
        Write-Host '[INFO] PostgreSQL start mode: direct'
        Start-PostgresDirect -PostgresExePath $postgresExe -PostgresDataDirPath $postgresDataDir -RuntimeRootPath $RuntimeRoot
        return
    }

    $manualOutLogFile = Join-Path $RuntimeRoot 'logs/postgres.manual.out.log'
    $manualErrLogFile = Join-Path $RuntimeRoot 'logs/postgres.manual.err.log'
    Remove-Item -LiteralPath $manualOutLogFile, $manualErrLogFile -Force -ErrorAction SilentlyContinue
    Write-Host '[INFO] Waiting for PostgreSQL startup acknowledgement...'
    $startArgs = @('-D', $postgresDataDir, '-l', $postgresLogFile, '-w', '-t', '30', 'start')
    $startProc = Start-Process -FilePath $pgCtl -ArgumentList $startArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $manualOutLogFile -RedirectStandardError $manualErrLogFile
    $pgCtlTimedOut = -not ($startProc.WaitForExit(45000))
    if ($pgCtlTimedOut) {
        Write-Host '[WARN] pg_ctl startup check exceeded 45 seconds; terminating pg_ctl process and evaluating fallback path...'
        Stop-Process -Id $startProc.Id -Force -ErrorAction SilentlyContinue
    }
    $pgCtlExitCode = if ($pgCtlTimedOut) { 124 } else { $startProc.ExitCode }

    if ($pgCtlExitCode -ne 0) {
        if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort)) {
            if (Wait-PostgresQueryReady -MaxSeconds 20) {
                Write-Host '[WARN] pg_ctl returned non-zero but PostgreSQL is reachable. Continuing startup.'
                return
            }
        }

        $manualErr = ''
        if (Test-Path $manualErrLogFile) {
            $manualErr = (Get-Content -Path $manualErrLogFile -Raw -ErrorAction SilentlyContinue)
        }

        if (($effectiveStartMode -eq 'auto') -and ($pgCtlTimedOut -or ($manualErr -and $manualErr.ToLower().Contains('could not create restricted token: error code 87')))) {
            if (-not (Test-Path $postgresExe)) {
                throw "pg_ctl failed with restricted-token error and postgres.exe is missing: $postgresExe"
            }

            if ($pgCtlTimedOut) {
                Write-Host '[WARN] pg_ctl timed out. Falling back to direct postgres.exe startup...'
            }
            else {
                Write-Host '[WARN] pg_ctl restricted-token issue detected (error 87). Falling back to direct postgres.exe startup...'
            }
            Start-PostgresDirect -PostgresExePath $postgresExe -PostgresDataDirPath $postgresDataDir -RuntimeRootPath $RuntimeRoot
            return
        }
        else {
            $logTail = ''
            if (Test-Path $manualErrLogFile) {
                $logTail = (Get-Content -Path $manualErrLogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            }
            if ((-not $logTail) -and (Test-Path $postgresLogFile)) {
                $logTail = (Get-Content -Path $postgresLogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            }
            if ($logTail) {
                throw "PostgreSQL start failed (pg_ctl exit=$pgCtlExitCode). Recent logs:`n$logTail"
            }
            throw "PostgreSQL start failed (pg_ctl exit=$pgCtlExitCode). Check $manualErrLogFile and $postgresLogFile"
        }
    }

    Wait-TcpPortReady -Name 'PostgreSQL' -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort) -MaxSeconds 30
    if (-not (Wait-PostgresQueryReady -MaxSeconds 45)) {
        $directErrLogFile = Join-Path $RuntimeRoot 'logs/postgres.direct.err.log'
        $logTail = ''
        if (Test-Path $directErrLogFile) {
            $logTail = (Get-Content -Path $directErrLogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        if ((-not $logTail) -and (Test-Path $postgresLogFile)) {
            $logTail = (Get-Content -Path $postgresLogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        if ($logTail) {
            throw "PostgreSQL started but SQL query check failed. Recent logs:`n$logTail"
        }
        throw 'PostgreSQL started but SQL query check failed. Check runtime postgres logs and credentials.'
    }
}

function Test-KafkaKRaftMode {
    $kafkaConfig = Join-Path $RuntimeRoot 'config/kafka/server.properties'
    if (-not (Test-Path $kafkaConfig)) {
        return $false
    }

    $content = Get-Content $kafkaConfig -Raw
    if ($content -match '(?m)^\s*process\.roles\s*=') {
        return $true
    }
    if ($content -match '(?m)^\s*controller\.quorum\.voters\s*=') {
        return $true
    }

    return $false
}

function Get-ZookeeperClientPort {
    $zookeeperConfig = Join-Path $KafkaDir 'config/zookeeper.properties'
    if (-not (Test-Path $zookeeperConfig)) {
        return [int]$ZookeeperPort
    }

    foreach ($line in (Get-Content $zookeeperConfig)) {
        if ($line -match '^\s*clientPort\s*=\s*(\d+)\s*$') {
            return [int]$Matches[1]
        }
    }

    return [int]$ZookeeperPort
}

function Test-PortOwnedByRuntimeProcess {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string[]]$MatchTokens
    )

    try {
        $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $listener) {
            return $false
        }

        $ownerPid = [int]$listener.OwningProcess
        if ($ownerPid -le 0) {
            return $false
        }

        $ownerProc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if (-not $ownerProc -or -not $ownerProc.CommandLine) {
            return $false
        }

        $cmdLower = "$($ownerProc.CommandLine)".ToLower().Replace('\', '/')
        foreach ($token in $MatchTokens) {
            if (-not $token) { continue }
            $tokenLower = $token.ToLower().Replace('\', '/')
            if ($cmdLower.Contains($tokenLower)) {
                return $true
            }
        }
    }
    catch {
    }

    return $false
}

function Get-InfraActiveReasons {
    $reasons = @()
    $zookeeperClientPort = Get-ZookeeperClientPort
    $postgresRuntimeToken = $PostgresDir.ToLower().Replace('\', '/')
    $kafkaRuntimeToken = $KafkaDir.ToLower().Replace('\', '/')

    # Check if Postgres port is occupied
    if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort)) {
        $reasons += "PostgreSQL port $PostgresPort is open/occupied"
    }

    # Check if Kafka port is occupied
    if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$KafkaPort)) {
        $reasons += "Kafka port $KafkaPort is open/occupied"
    }

    # Check if Zookeeper port is occupied (if not KRaft mode)
    if (-not (Test-KafkaKRaftMode)) {
        if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$zookeeperClientPort)) {
            $reasons += "Zookeeper port $zookeeperClientPort is open/occupied"
        }
    }

    $runtimeRunDir = Join-Path $RuntimeRoot 'run'
    $kafkaPidFile = Join-Path $runtimeRunDir 'kafka.pid'
    $zookeeperPidFile = Join-Path $runtimeRunDir 'zookeeper.pid'
    $postgresPidFile = Join-Path $runtimeRunDir 'postgres.pid'

    if (Test-PidFileProcessRunning -PidFilePath $kafkaPidFile) {
        $reasons += "Kafka PID file points to a running process ($kafkaPidFile)"
    }
    if (Test-PidFileProcessRunning -PidFilePath $zookeeperPidFile) {
        $reasons += "Zookeeper PID file points to a running process ($zookeeperPidFile)"
    }
    if (Test-PidFileProcessRunning -PidFilePath $postgresPidFile) {
        $reasons += "PostgreSQL PID file points to a running process ($postgresPidFile)"
    }

    # Also check processes directly running from runtime directories as a fallback
    $postgresProcs = Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $postgresProcs) {
        $cmd = "$($proc.CommandLine)"
        if ($cmd -and $cmd.ToLower().Replace('\', '/').Contains($postgresRuntimeToken)) {
            $reasons += "PostgreSQL process is running from runtime path (PID=$($proc.ProcessId))"
            break
        }
    }

    $javaProcs = Get-CimInstance Win32_Process -Filter "Name='java.exe'" -ErrorAction SilentlyContinue
    foreach ($proc in $javaProcs) {
        $cmd = "$($proc.CommandLine)"
        if ($cmd -and $cmd.ToLower().Replace('\', '/').Contains($kafkaRuntimeToken)) {
            $reasons += "Java/Kafka process is running from runtime path (PID=$($proc.ProcessId))"
            break
        }
    }

    return $reasons
}

function Invoke-InfraResetIfNeeded {
    $reasons = Get-InfraActiveReasons
    if ($reasons.Count -eq 0) {
        Write-Host '[OK] No running local infra detected before startup'
        return
    }

    Write-Host '[WARN] Existing local infra detected. Running stop_infra.ps1 before startup...'
    foreach ($reason in $reasons) {
        Write-Host "  - $reason"
    }

    if (-not (Test-Path $StopInfraScript)) {
        throw "Missing stop script: $StopInfraScript"
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File $StopInfraScript
    if ($LASTEXITCODE -ne 0) {
        throw "stop_infra.ps1 failed with exit code $LASTEXITCODE"
    }

    $zookeeperClientPort = Get-ZookeeperClientPort
    if (-not (Wait-TcpPortClosed -Name 'PostgreSQL' -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort) -MaxSeconds 25)) {
        throw "PostgreSQL port $PostgresPort is still open after stop_infra"
    }
    if (-not (Wait-TcpPortClosed -Name 'Kafka' -TargetHost '127.0.0.1' -TargetPort ([int]$KafkaPort) -MaxSeconds 25)) {
        throw "Kafka port $KafkaPort is still open after stop_infra"
    }
    if ((-not (Test-KafkaKRaftMode)) -and (-not (Wait-TcpPortClosed -Name 'Zookeeper' -TargetHost '127.0.0.1' -TargetPort ([int]$zookeeperClientPort) -MaxSeconds 25))) {
        throw "Zookeeper port $zookeeperClientPort is still open after stop_infra"
    }

    Write-Host '[OK] Existing local infra was stopped successfully'
}

function Start-ZookeeperIfNeeded {
    if (Test-KafkaKRaftMode) {
        Write-Host '[INFO] Kafka is running in KRaft mode. Skipping Zookeeper startup.'
        return
    }

    $zookeeperConfig = Join-Path $KafkaDir 'config/zookeeper.properties'
    $zookeeperPidFile = Join-Path $RuntimeRoot 'run/zookeeper.pid'
    $zookeeperLogFile = Join-Path $RuntimeRoot 'logs/zookeeper.log'
    $zookeeperErrLogFile = Join-Path $RuntimeRoot 'logs/zookeeper.err.log'
    $zookeeperClientPort = Get-ZookeeperClientPort

    $javaExe = Join-Path $JavaDir 'bin/java.exe'
    $kafkaLibs = Join-Path $KafkaDir 'libs/*'

    if (-not (Test-Path $javaExe)) {
        throw "Missing Java runtime: $javaExe"
    }
    if (-not (Test-Path (Join-Path $KafkaDir 'libs'))) {
        throw "Missing Kafka libs directory: $(Join-Path $KafkaDir 'libs')"
    }
    if (-not (Test-Path $zookeeperConfig)) {
        throw "Missing Zookeeper config: $zookeeperConfig"
    }

    if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort $zookeeperClientPort) {
        Write-Host "[OK] Zookeeper is already running on port $zookeeperClientPort"
        return
    }

    Write-Host '[INFO] Starting Zookeeper in background...'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $zookeeperPidFile), (Split-Path -Parent $zookeeperLogFile) | Out-Null
    $zkProc = Start-Process -FilePath $javaExe -ArgumentList @('-cp', $kafkaLibs, 'org.apache.zookeeper.server.quorum.QuorumPeerMain', $zookeeperConfig) -RedirectStandardOutput $zookeeperLogFile -RedirectStandardError $zookeeperErrLogFile -PassThru -WindowStyle Hidden
    Set-Content -Path $zookeeperPidFile -Value $zkProc.Id -Encoding UTF8

    Wait-TcpPortReady -Name 'Zookeeper' -TargetHost '127.0.0.1' -TargetPort $zookeeperClientPort -MaxSeconds 45
}

function Start-KafkaIfNeeded {
    $kafkaConfig = Join-Path $RuntimeRoot 'config/kafka/server.properties'
    $kafkaPidFile = Join-Path $RuntimeRoot 'run/kafka.pid'
    $kafkaLogFile = Join-Path $RuntimeRoot 'logs/kafka.log'
    $kafkaErrLogFile = Join-Path $RuntimeRoot 'logs/kafka.err.log'

    $javaExe = Join-Path $JavaDir 'bin/java.exe'
    $kafkaLibs = Join-Path $KafkaDir 'libs/*'

    $kafkaDataDir = Join-Path $RuntimeRoot 'kafka-data'
    $staleFiles = Get-ChildItem -Path $kafkaDataDir -Recurse -Filter '*.deleted' -ErrorAction SilentlyContinue
    if ($staleFiles) {
        Write-Host "[INFO] Cleaning $($staleFiles.Count) stale .deleted files from kafka-data (Windows file-lock workaround)"
        $staleFiles | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue | Out-Null
        }
    }

    function Add-KafkaConfigIfMissing {
        param([string]$ConfigPath, [string]$Setting)
        $content = Get-Content -Path $ConfigPath -Raw -ErrorAction SilentlyContinue
        $key = ($Setting -split '=')[0]
        if ($content -and $content -notmatch [Regex]::Escape($key)) {
            Write-Host "[INFO] Adding $key to Kafka config"
            Add-Content -Path $ConfigPath -Value $Setting -Encoding UTF8
        }
    }

    Add-KafkaConfigIfMissing -ConfigPath $kafkaConfig -Setting "log.cleaner.enable=false"
    Add-KafkaConfigIfMissing -ConfigPath $kafkaConfig -Setting "log.retention.hours=87600"
    Add-KafkaConfigIfMissing -ConfigPath $kafkaConfig -Setting "log.retention.check.interval.ms=2592000000"
    Add-KafkaConfigIfMissing -ConfigPath $kafkaConfig -Setting "log.segment.delete.delay.ms=60000"
    Add-KafkaConfigIfMissing -ConfigPath $kafkaConfig -Setting "file.delete.delay.ms=60000"

    if (-not (Test-Path $javaExe)) {
        throw "Missing Java runtime: $javaExe"
    }
    if (-not (Test-Path (Join-Path $KafkaDir 'libs'))) {
        throw "Missing Kafka libs directory: $(Join-Path $KafkaDir 'libs')"
    }
    if (-not (Test-Path $kafkaConfig)) {
        throw "Missing Kafka config: $kafkaConfig"
    }

    if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$KafkaPort)) {
        Write-Host '[OK] Kafka is already running'
        return
    }

    $log4jFile = Join-Path $RuntimeRoot 'config/kafka/log4j.properties'
    if (-not (Test-Path $log4jFile)) {
        $log4jFile = Join-Path $KafkaDir 'config/log4j.properties'
    }
    $kafkaLogsDir = Split-Path -Parent $kafkaLogFile

    Write-Host '[INFO] Starting Kafka in background...'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $kafkaPidFile), $kafkaLogsDir | Out-Null
    $env:JAVA_HOME = $JavaDir
    $kafkaArgs = @()
    if (Test-Path $log4jFile) {
        $kafkaArgs += "-Dlog4j.configuration=file:$log4jFile"
        $kafkaArgs += "-Dkafka.logs.dir=$kafkaLogsDir"
    }
    $kafkaArgs += @('-cp', $kafkaLibs, 'kafka.Kafka', $kafkaConfig)
    $kafkaProc = Start-Process -FilePath $javaExe -ArgumentList $kafkaArgs -RedirectStandardOutput $kafkaLogFile -RedirectStandardError $kafkaErrLogFile -PassThru -WindowStyle Hidden
    Set-Content -Path $kafkaPidFile -Value $kafkaProc.Id -Encoding UTF8

    Wait-TcpPortReady -Name 'Kafka' -TargetHost '127.0.0.1' -TargetPort ([int]$KafkaPort) -MaxSeconds 60
}

function Start-LocalInfra {
    Start-PostgresIfNeeded
    Start-ZookeeperIfNeeded
    Start-KafkaIfNeeded
}

Initialize-Runtime
Update-RuntimePortsFromCredentials
Invoke-InfraResetIfNeeded
Sync-RuntimeEnv
Start-LocalInfra

$env:JAVA_HOME = $JavaDir
$env:Path = "$JavaDir\bin;$PostgresDir\bin;$env:Path"

Write-Host '[INFO] Verifying core dependencies...'
& $venvPy -c "import importlib; [importlib.import_module(m) for m in ('google.genai','discord','dotenv','flask','aiohttp','cryptography','openai','asyncpg','aiokafka')]"
if ($LASTEXITCODE -ne 0) {
    Write-Host '[INFO] Installing/updating requirements...'
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
}

$envFile = Join-Path $ProjectRoot '.env'
if (-not (Test-Path $envFile)) {
    throw '.env is missing even after runtime sync'
}

Write-Host '[INFO] Running runtime preflight...'
& $venvPy (Join-Path $ProjectRoot 'run_bot.py') --preflight
if ($LASTEXITCODE -ne 0) {
    throw 'Preflight failed'
}
Write-Host '[OK] Preflight passed'

if ($PreflightOnly) {
    Write-Host '[INFO] Preflight-only mode complete.'
    exit 0
}

$tokenConfigured = $false
foreach ($line in (Get-Content $envFile)) {
    if ($line -match '^DISCORD_TOKEN=.+$') {
        $tokenConfigured = $true
        break
    }
}
if (-not $tokenConfigured) {
    throw 'DISCORD_TOKEN is missing in .env. Please set your real token, then rerun.'
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if ($Pm2Mode) {
    $pm2Cmd = Get-Command pm2 -ErrorAction SilentlyContinue
    if ($null -eq $pm2Cmd) {
        throw 'pm2 not found. Install with: npm i -g pm2'
    }

    if (-not (Test-Path $EcosystemFile)) {
        throw "Missing $EcosystemFile"
    }

    if ($Pm2Fresh) {
        pm2 update
        pm2 delete $AppName
    }

    pm2 start $EcosystemFile --only $AppName --update-env
    pm2 save
    Write-Host '[OK] PM2 app started'
    exit 0
}

& $venvPy (Join-Path $ProjectRoot 'run_bot.py')
