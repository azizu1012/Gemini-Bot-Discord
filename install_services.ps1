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

$JavaDir = Join-Path $RuntimeRoot 'java'
$KafkaDir = Join-Path $RuntimeRoot 'kafka'
$PostgresDir = Join-Path $RuntimeRoot 'postgres'
$PostgresDataDir = Join-Path $PostgresDir 'data'
$PostgresLogFile = Join-Path $LogsDir 'postgres.log'
$KafkaLogFile = Join-Path $LogsDir 'kafka.log'
$KafkaErrLogFile = Join-Path $LogsDir 'kafka.err.log'
$PostgresCredentialsFile = Join-Path $PostgresDir 'credentials.env'
$PostgresPidFile = Join-Path $RunDir 'postgres.pid'

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
$KafkaPort = if ($env:KAFKA_PORT) { $env:KAFKA_PORT } else { '59092' }
$KafkaControllerPort = if ($env:KAFKA_CONTROLLER_PORT) { $env:KAFKA_CONTROLLER_PORT } else { '59093' }
$KafkaClusterIdFile = Join-Path $RuntimeRoot 'kafka.cluster_id'
$KafkaClusterId = if ($env:KAFKA_CLUSTER_ID) { $env:KAFKA_CLUSTER_ID } else { 'AzurisLocalCluster0001' }

$JavaDownloadUrl = if ($env:JAVA_DOWNLOAD_URL) { $env:JAVA_DOWNLOAD_URL } else { 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse' }
$KafkaVersion = if ($env:KAFKA_VERSION) { $env:KAFKA_VERSION } else { '3.7.0' }
$ScalaVersion = if ($env:SCALA_VERSION) { $env:SCALA_VERSION } else { '2.13' }
$KafkaDownloadUrl = if ($env:KAFKA_DOWNLOAD_URL) { $env:KAFKA_DOWNLOAD_URL } else { "https://downloads.apache.org/kafka/$KafkaVersion/kafka_${ScalaVersion}-${KafkaVersion}.tgz" }
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

function Install-Java {
    $javaExe = Join-Path $JavaDir 'bin/java.exe'
    if (Test-Path $javaExe) {
        Write-Info "Java already installed at $JavaDir"
        return
    }

    $archive = Join-Path $DownloadsDir 'java-windows-x64.zip'
    $javaUrlCandidates = @(
        $JavaDownloadUrl,
        'https://github.com/adoptium/temurin17-binaries/releases/latest/download/OpenJDK17U-jdk_x64_windows_hotspot.zip'
    )

    $installed = $false
    foreach ($candidate in $javaUrlCandidates) {
        $tempDir = Join-Path $env:TEMP ("azuris-java-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempDir | Out-Null

        try {
            if (Test-Path $archive) {
                Remove-Item $archive -Force
            }

            Get-FileIfMissing $candidate $archive
            Expand-Archive -Path $archive -DestinationPath $tempDir -Force
            Move-ExtractedChildToTarget $tempDir $JavaDir
            $installed = $true
            Remove-Item -Recurse -Force $tempDir
            break
        }
        catch {
            Write-WarnMsg "Java install attempt failed from: $candidate"
            if (Test-Path $archive) {
                Remove-Item $archive -Force
            }
            if (Test-Path $tempDir) {
                Remove-Item -Recurse -Force $tempDir
            }
        }
    }

    if (-not $installed) {
        throw 'Failed to download/extract Java from all configured sources.'
    }

    Write-Info "Installed Java at $JavaDir"
}

function Install-Kafka {
    $kafkaStart = Join-Path $KafkaDir 'bin/windows/kafka-server-start.bat'
    if (Test-Path $kafkaStart) {
        Write-Info "Kafka already installed at $KafkaDir"
        return
    }

    $archive = Join-Path $DownloadsDir "kafka_${ScalaVersion}-${KafkaVersion}.tgz"
    $kafkaUrlCandidates = @(
        $KafkaDownloadUrl,
        "https://archive.apache.org/dist/kafka/$KafkaVersion/kafka_${ScalaVersion}-${KafkaVersion}.tgz"
    )

    $installed = $false
    foreach ($candidate in $kafkaUrlCandidates) {
        $tempDir = Join-Path $env:TEMP ("azuris-kafka-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempDir | Out-Null

        try {
            if (Test-Path $archive) {
                Remove-Item $archive -Force
            }

            Get-FileIfMissing $candidate $archive
            tar -xzf $archive -C $tempDir
            Move-ExtractedChildToTarget $tempDir $KafkaDir
            $installed = $true
            Remove-Item -Recurse -Force $tempDir
            break
        }
        catch {
            Write-WarnMsg "Kafka install attempt failed from: $candidate"
            if (Test-Path $archive) {
                Remove-Item $archive -Force
            }
            if (Test-Path $tempDir) {
                Remove-Item -Recurse -Force $tempDir
            }
        }
    }

    if (-not $installed) {
        throw 'Failed to download/extract Kafka from all configured sources.'
    }

    Write-Info "Installed Kafka at $KafkaDir"
}

function Update-KafkaWindowsScripts {
    $kafkaStartScript = Join-Path $KafkaDir 'bin/windows/kafka-server-start.bat'
    if (-not (Test-Path $kafkaStartScript)) {
        return
    }

    $originalLine = 'wmic os get osarchitecture | find /i "32-bit" >nul 2>&1'
    $replacementLine = 'cmd /c exit /b 1'
    $content = Get-Content -Path $kafkaStartScript -Raw

    if ($content -like "*$originalLine*") {
        $patched = $content -replace [Regex]::Escape($originalLine), $replacementLine
        Write-Utf8NoBom -Path $kafkaStartScript -Content $patched
        Write-Info 'Patched kafka-server-start.bat to remove WMIC dependency'
    }
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

function Initialize-KafkaConfig {
    Write-Info 'Generating Kafka KRaft configuration'
    $kafkaConfigDir = Join-Path $ConfigDir 'kafka'
    $kafkaDataDir = Join-Path $RuntimeRoot 'kafka-data'
    New-Item -ItemType Directory -Force -Path $kafkaConfigDir, $kafkaDataDir | Out-Null

    $kafkaDataDirForward = ($kafkaDataDir -replace '\\', '/')

    $kafkaConfigContent = @"
process.roles=broker,controller
node.id=1
listeners=PLAINTEXT://127.0.0.1:$KafkaPort,CONTROLLER://127.0.0.1:$KafkaControllerPort
advertised.listeners=PLAINTEXT://127.0.0.1:$KafkaPort
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
controller.quorum.voters=1@127.0.0.1:$KafkaControllerPort
num.network.threads=3
num.io.threads=8
socket.send.buffer.bytes=102400
socket.receive.buffer.bytes=102400
socket.request.max.bytes=104857600
log.dirs=$kafkaDataDirForward
num.partitions=3
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
group.initial.rebalance.delay.ms=0
auto.create.topics.enable=true
"@

    Write-Utf8NoBom -Path (Join-Path $kafkaConfigDir 'server.properties') -Content $kafkaConfigContent
}

function Start-KafkaIfNeeded {
    $kafkaConfig = Join-Path $ConfigDir 'kafka/server.properties'
    $kafkaDataMeta = Join-Path $RuntimeRoot 'kafka-data/meta.properties'
    $kafkaPidFile = Join-Path $RunDir 'kafka.pid'

    if (-not (Test-Path $kafkaConfig)) {
        throw "Kafka config file missing: $kafkaConfig"
    }

    if (-not (Test-Path $KafkaClusterIdFile)) {
        Write-Utf8NoBom -Path $KafkaClusterIdFile -Content ($KafkaClusterId + "`n")
    }

    $javaExe = Join-Path $JavaDir 'bin/java.exe'
    $kafkaLibs = Join-Path $KafkaDir 'libs/*'

    if (-not (Test-Path $javaExe)) {
        throw "Java runtime missing: $javaExe"
    }

    if (-not (Test-Path (Join-Path $KafkaDir 'libs'))) {
        throw "Kafka libs directory missing: $(Join-Path $KafkaDir 'libs')"
    }

    if (-not (Test-Path $kafkaDataMeta)) {
        Write-Info 'Formatting Kafka KRaft storage'
        $env:JAVA_HOME = $JavaDir
        $clusterId = (Get-Content $KafkaClusterIdFile).Trim()
        $formatOutput = & $javaExe -cp $kafkaLibs kafka.tools.StorageTool format -t $clusterId -c $kafkaConfig
        $formatOutputText = "$formatOutput"

        if (($LASTEXITCODE -ne 0) -or ($formatOutputText -match 'Exception') -or (-not (Test-Path $kafkaDataMeta))) {
            if ($formatOutputText -match 'cluster.id' -or $formatOutputText -match 'cluster ID' -or $formatOutputText -match 'Invalid') {
                Write-WarnMsg 'Kafka cluster id appears invalid, generating a new one.'
                $clusterId = (& $javaExe -cp $kafkaLibs kafka.tools.StorageTool random-uuid).Trim()
                if (-not $clusterId) {
                    throw 'Kafka random-uuid generation failed on Windows.'
                }
                Write-Utf8NoBom -Path $KafkaClusterIdFile -Content ($clusterId + "`n")
                $formatOutput = & $javaExe -cp $kafkaLibs kafka.tools.StorageTool format -t $clusterId -c $kafkaConfig
                $formatOutputText = "$formatOutput"
            }
        }

        if (($LASTEXITCODE -ne 0) -or ($formatOutputText -match 'Exception') -or (-not (Test-Path $kafkaDataMeta))) {
            throw 'Kafka storage format failed on Windows.'
        }
    }

    if (Test-Path $kafkaPidFile) {
        $existingPid = (Get-Content $kafkaPidFile).Trim()
        if ($existingPid) {
            $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Info 'Kafka already running'
            }
            else {
                Remove-Item $kafkaPidFile -Force
            }
        }
    }

    if (-not (Test-Path $kafkaPidFile)) {
        Write-Info 'Starting Kafka broker process'
        $env:JAVA_HOME = $JavaDir
        $proc = Start-Process -FilePath $javaExe -ArgumentList @('-cp', $kafkaLibs, 'kafka.Kafka', $kafkaConfig) -RedirectStandardOutput $KafkaLogFile -RedirectStandardError $KafkaErrLogFile -PassThru -WindowStyle Hidden
        Set-Content -Path $kafkaPidFile -Value $proc.Id -Encoding UTF8
    }

    Write-Info 'Waiting for Kafka port readiness'
    $ready = $false
    for ($i = 0; $i -lt 45; $i++) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $async = $client.BeginConnect('127.0.0.1', [int]$KafkaPort, $null, $null)
            $connected = $async.AsyncWaitHandle.WaitOne(1000, $false)
            if ($connected -and $client.Connected) {
                $client.EndConnect($async)
                $ready = $true
                break
            }
        }
        finally {
            $client.Close()
        }
        Start-Sleep -Seconds 1
    }

    if (-not $ready) {
        throw "Kafka failed to become ready. Check $KafkaLogFile"
    }

}

function Update-EnvFile($DatabaseUrl) {
    $envFile = Join-Path $ProjectRoot '.env'
    Remove-EnvBackups
    Set-EnvValue -EnvFile $envFile -Key 'LOCAL_RUNTIME_ROOT' -Value $RuntimeRootEnvValue
    Set-EnvValue -EnvFile $envFile -Key 'JAVA_HOME' -Value $JavaDir
    Set-EnvValue -EnvFile $envFile -Key 'KAFKA_BOOTSTRAP_SERVERS' -Value "127.0.0.1:$KafkaPort"
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
Install-Java
Install-Kafka
Update-KafkaWindowsScripts
Install-Postgres
Initialize-PostgresData
Initialize-PostgresRuntime
Initialize-KafkaConfig
Start-KafkaIfNeeded

Write-Info 'Completed local runtime setup.'
Write-Host 'DATABASE_URL and KAFKA_BOOTSTRAP_SERVERS have been synced to .env'
Write-Host "PostgreSQL: 127.0.0.1:$PostgresPort"
Write-Host "Kafka: 127.0.0.1:$KafkaPort"
