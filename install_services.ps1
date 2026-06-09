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

$RuntimeRoot = if ([System.IO.Path]::IsPathRooted($RuntimeRootEnvValue)) {
    [System.IO.Path]::GetFullPath($RuntimeRootEnvValue)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RuntimeRootEnvValue))
}
$env:LOCAL_RUNTIME_ROOT = $RuntimeRootEnvValue

$DownloadsDir = Join-Path $RuntimeRoot 'downloads'
$ConfigDir = Join-Path $RuntimeRoot 'config'
$LogsDir = Join-Path $RuntimeRoot 'logs'
$RunDir = Join-Path $RuntimeRoot 'run'

$PostgresDir = Join-Path $RuntimeRoot 'postgres'
$PostgresDataDir = Join-Path $PostgresDir 'data'
$PostgresLogFile = Join-Path $LogsDir 'postgres.log'
$PostgresCredentialsFile = Join-Path $PostgresDir 'credentials.env'
$PostgresPidFile = Join-Path $RunDir 'postgres.pid'

$RedisDir = Join-Path $RuntimeRoot 'redis'
$RedisLogFile = Join-Path $LogsDir 'redis.log'
$RedisErrLogFile = Join-Path $LogsDir 'redis.err.log'

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

$PostgresPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { '55432' }
$PostgresDownloadUrl = if ($env:POSTGRES_DOWNLOAD_URL) { $env:POSTGRES_DOWNLOAD_URL } else { 'https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip' }

$VenvPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { 'python' }

New-Item -ItemType Directory -Force -Path $DownloadsDir, $ConfigDir, $LogsDir, $RunDir | Out-Null

function Write-Info($Message) {
    Write-Host "[install_services.ps1] $Message" -ForegroundColor Green
}

function Write-WarnMsg($Message) {
    Write-Host "[install_services.ps1] $Message" -ForegroundColor Yellow
}

function Assert-Command($Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw "Missing required command: $Name"
    }
}

function Get-FileIfMissing($Url, $OutFile) {
    if (Test-Path $OutFile) {
        Write-Info "Using cached file: $OutFile"
        return
    }

    Write-Info "Downloading: $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
    }
    catch {
        if (Test-Path $OutFile) {
            Remove-Item $OutFile -Force
        }
        throw
    }
}

function Move-ExtractedChildToTarget($TempDir, $TargetDir) {
    if (Test-Path $TargetDir) {
        Write-Info "Already exists: $TargetDir"
        return
    }

    $children = Get-ChildItem -Path $TempDir -Directory
    if ($children.Count -eq 0) {
        throw "Archive did not contain a top-level directory"
    }

    Move-Item -Path $children[0].FullName -Destination $TargetDir
}

function Write-Utf8NoBom($Path, $Content) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
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
        [int]$MaxSeconds = 30
    )

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (Test-TcpPortReady -TargetHost $TargetHost -TargetPort $TargetPort) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    throw "$Name is not ready on $TargetHost`:$TargetPort after $MaxSeconds seconds"
}





function Install-Postgres {
    $initdb = Join-Path $PostgresDir 'bin/initdb.exe'
    if (Test-Path $initdb) {
        Write-Info "PostgreSQL already installed at $PostgresDir"
        return
    }

    $archive = Join-Path $DownloadsDir 'postgresql-windows-x64-binaries.zip'
    Get-FileIfMissing $PostgresDownloadUrl $archive

    New-Item -ItemType Directory -Force -Path $PostgresDir | Out-Null
    Expand-Archive -Path $archive -DestinationPath $PostgresDir -Force

    $nestedInitdb = Join-Path $PostgresDir 'pgsql/bin/initdb.exe'
    if ((-not (Test-Path $initdb)) -and (Test-Path $nestedInitdb)) {
        Get-ChildItem -Path (Join-Path $PostgresDir 'pgsql') | ForEach-Object {
            Move-Item -Path $_.FullName -Destination $PostgresDir -Force
        }
        Remove-Item -Recurse -Force (Join-Path $PostgresDir 'pgsql')
    }

    if (-not (Test-Path $initdb)) {
        throw 'PostgreSQL binaries were not extracted correctly. Set POSTGRES_DOWNLOAD_URL and rerun.'
    }

    Write-Info "Installed PostgreSQL at $PostgresDir"
}

function Start-PostgresDirect {
    $postgresExe = Join-Path $PostgresDir 'bin/postgres.exe'
    if (-not (Test-Path $postgresExe)) {
        throw "Missing postgres.exe for direct startup: $postgresExe"
    }

    Write-Info 'Starting PostgreSQL in direct mode'
    New-Item -ItemType Directory -Force -Path $LogsDir, $RunDir | Out-Null
    $directOutLogFile = Join-Path $LogsDir 'postgres.direct.out.log'
    $directErrLogFile = Join-Path $LogsDir 'postgres.direct.err.log'
    Remove-Item -LiteralPath $directOutLogFile, $directErrLogFile -Force -ErrorAction SilentlyContinue

    $proc = Start-Process -FilePath $postgresExe -ArgumentList @('-D', $PostgresDataDir, '-p', "$PostgresPort") -PassThru -WindowStyle Hidden -RedirectStandardOutput $directOutLogFile -RedirectStandardError $directErrLogFile
    Set-Content -Path $PostgresPidFile -Value $proc.Id -Encoding UTF8
    Wait-TcpPortReady -Name 'PostgreSQL' -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort) -MaxSeconds 30
}

function Stop-PostgresIfRunning {
    $pgCtl = Join-Path $PostgresDir 'bin/pg_ctl.exe'
    if ($PostgresStartMode -ne 'direct' -and (Test-Path $pgCtl) -and (Test-Path $PostgresDataDir)) {
        & $pgCtl -D $PostgresDataDir status *> $null
        if ($LASTEXITCODE -eq 0) {
            & $pgCtl -D $PostgresDataDir stop -m fast *> $null
        }
    }
}

function Initialize-PostgresData {
    $pgVersion = Join-Path $PostgresDataDir 'PG_VERSION'
    if (Test-Path $pgVersion) {
        Write-Info 'PostgreSQL data directory already initialized'
        return
    }

    $initdb = Join-Path $PostgresDir 'bin/initdb.exe'
    New-Item -ItemType Directory -Force -Path $PostgresDataDir | Out-Null
    & $initdb -D $PostgresDataDir -U postgres -A trust | Out-Null

    Add-Content -Path (Join-Path $PostgresDataDir 'postgresql.conf') -Value "listen_addresses = '127.0.0.1'"
    Add-Content -Path (Join-Path $PostgresDataDir 'postgresql.conf') -Value "port = $PostgresPort"
    Add-Content -Path (Join-Path $PostgresDataDir 'postgresql.conf') -Value "unix_socket_directories = ''"
    Add-Content -Path (Join-Path $PostgresDataDir 'pg_hba.conf') -Value 'host all all 127.0.0.1/32 md5'
    Add-Content -Path (Join-Path $PostgresDataDir 'pg_hba.conf') -Value 'host all all ::1/128 md5'

    Write-Info 'Initialized PostgreSQL data directory'
}

function Initialize-PostgresRuntime {
    $pgCtl = Join-Path $PostgresDir 'bin/pg_ctl.exe'
    $psql = Join-Path $PostgresDir 'bin/psql.exe'

    $pgCtlAvailable = Test-Path $pgCtl
    $effectiveStartMode = $PostgresStartMode
    if (-not $pgCtlAvailable) {
        if ($effectiveStartMode -eq 'auto') {
            Write-WarnMsg 'pg_ctl is missing. Falling back to direct postgres.exe startup.'
            $effectiveStartMode = 'direct'
        }
        elseif ($effectiveStartMode -eq 'pg_ctl') {
            throw "Missing PostgreSQL control binary: $pgCtl"
        }
    }

    Write-Info 'Ensuring PostgreSQL process is running'
    if ($effectiveStartMode -eq 'direct') {
        if (-not (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort ([int]$PostgresPort))) {
            Start-PostgresDirect
        }
        else {
            Write-Info 'PostgreSQL already running (port check)'
        }
    }
    else {
        if (-not $pgCtlAvailable) {
            throw "Missing PostgreSQL control binary: $pgCtl"
        }

        & $pgCtl -D $PostgresDataDir status *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Info 'Starting PostgreSQL process'
            & $pgCtl -D $PostgresDataDir -l $PostgresLogFile start
        }

        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            & $pgCtl -D $PostgresDataDir status *> $null
            if ($LASTEXITCODE -eq 0) {
                $ready = $true
                break
            }
            Start-Sleep -Seconds 1
        }

        if (-not $ready) {
            throw "PostgreSQL failed to start. Check $PostgresLogFile"
        }
    }

    Write-Info 'Generating PostgreSQL application password'
    $generatedPassword = & $PythonExe -c "import secrets; print(secrets.token_urlsafe(24))"

    Write-Info 'Ensuring azuris role exists'
    $roleExistsRaw = & $psql -h 127.0.0.1 -p $PostgresPort -U postgres -w -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='azuris'"
    $roleExists = "$roleExistsRaw".Trim()
    if ($roleExists -eq '1') {
        & $psql -h 127.0.0.1 -p $PostgresPort -U postgres -w -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE azuris WITH PASSWORD '$generatedPassword';" | Out-Null
    }
    else {
        & $psql -h 127.0.0.1 -p $PostgresPort -U postgres -w -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE azuris LOGIN PASSWORD '$generatedPassword';" | Out-Null
    }

    Write-Info 'Ensuring azuris database exists'
    $dbExistsRaw = & $psql -h 127.0.0.1 -p $PostgresPort -U postgres -w -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='azuris'"
    $dbExists = "$dbExistsRaw".Trim()
    if ($dbExists -ne '1') {
        & $psql -h 127.0.0.1 -p $PostgresPort -U postgres -w -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE azuris OWNER azuris;" | Out-Null
    }

    Write-Info 'Ensuring pg_trgm extension exists'
    & $psql -h 127.0.0.1 -p $PostgresPort -U postgres -w -d azuris -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;' | Out-Null

    @(
        "AZURIS_DB_USER=azuris"
        "AZURIS_DB_PASSWORD=$generatedPassword"
        "AZURIS_DB_NAME=azuris"
        "AZURIS_DB_PORT=$PostgresPort"
    ) | Set-Content -Path $PostgresCredentialsFile -Encoding UTF8

    $databaseUrl = "postgresql://azuris:$generatedPassword@127.0.0.1:$PostgresPort/azuris?sslmode=disable"
    Write-Info 'Syncing runtime database settings into .env'
    Update-EnvFile $databaseUrl
}

function Install-Redis {
    $redisExe = Join-Path $RedisDir 'redis-server.exe'
    if (Test-Path $redisExe) {
        Write-Info "Redis already installed at $RedisDir"
        return
    }

    $archive = Join-Path $DownloadsDir 'redis-windows-x64.zip'
    $redisUrl = 'https://github.com/microsoftarchive/redis/releases/download/win-3.2.100/Redis-x64-3.2.100.zip'

    New-Item -ItemType Directory -Force -Path $RedisDir | Out-Null
    Get-FileIfMissing $redisUrl $archive
    Expand-Archive -Path $archive -DestinationPath $RedisDir -Force

    $redisConf = @"
port 6379
bind 127.0.0.1
daemonize no
save ""
appendonly no
"@
    Write-Utf8NoBom -Path (Join-Path $RedisDir 'redis.conf') -Content $redisConf

    if (-not (Test-Path $redisExe)) {
        throw 'Redis binaries were not extracted correctly.'
    }

    Write-Info "Installed Redis at $RedisDir"
}

function Start-RedisIfNeeded {
    $redisExe = Join-Path $RedisDir 'redis-server.exe'
    $redisPidFile = Join-Path $RunDir 'redis.pid'
    $redisConf = Join-Path $RedisDir 'redis.conf'

    if (-not (Test-Path $redisExe)) {
        throw "Missing Redis executable: $redisExe"
    }

    New-Item -ItemType Directory -Force -Path $RunDir, $LogsDir | Out-Null

    if (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort 6379) {
        Write-Info 'Redis is already running on port 6379'
        return
    }

    Write-Info 'Starting Redis server'
    Remove-Item -LiteralPath $RedisLogFile, $RedisErrLogFile -Force -ErrorAction SilentlyContinue

    $proc = Start-Process -FilePath $redisExe -ArgumentList $redisConf -PassThru -WindowStyle Hidden -RedirectStandardOutput $RedisLogFile -RedirectStandardError $RedisErrLogFile
    Set-Content -Path $redisPidFile -Value $proc.Id -Encoding UTF8

    Start-Sleep -Seconds 3

    if (-not (Test-TcpPortReady -TargetHost '127.0.0.1' -TargetPort 6379)) {
        throw "Redis failed to start on port 6379. Check $RedisErrLogFile"
    }

    Write-Info 'Redis is ready on port 6379'
}

function Update-EnvFile($DatabaseUrl) {
    $envFile = Join-Path $ProjectRoot '.env'
    Remove-EnvBackups
    Set-EnvValue -EnvFile $envFile -Key 'LOCAL_RUNTIME_ROOT' -Value $RuntimeRootEnvValue
    Set-EnvValue -EnvFile $envFile -Key 'DATABASE_URL' -Value $DatabaseUrl
    Remove-EnvBackups
}

if ($PythonExe -eq 'python') {
    Assert-Command python
}
Assert-Command tar

Write-Info "Project root: $ProjectRoot"
Write-Info "Runtime root: $RuntimeRoot"

Stop-PostgresIfRunning
Install-Postgres
Initialize-PostgresData
Initialize-PostgresRuntime
Install-Redis
Start-RedisIfNeeded

Write-Info 'Completed local runtime setup.'
Write-Host 'DATABASE_URL has been synced to .env'
Write-Host "PostgreSQL: 127.0.0.1:$PostgresPort"
