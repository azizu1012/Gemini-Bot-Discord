# Azuris Docker runner — 1 lệnh duy nhất để chạy bot TRONG Docker.
#   .\run_bot.ps1              # build (nếu cần) + start toàn stack
#   .\run_bot.ps1 up           # như trên
#   .\run_bot.ps1 down         # tắt hết, giữ data
#   .\run_bot.ps1 stop-bot     # chỉ tắt bot (giữ infra postgres/redis chạy)
#   .\run_bot.ps1 stop-infra   # chỉ tắt infra (giữ container, data an toàn)
#   .\run_bot.ps1 rebuild      # build lại + recreate container
#   .\run_bot.ps1 restart      # restart service bot
#   .\run_bot.ps1 logs [svc]   # xem log (mặc định bot, -f follow)
#   .\run_bot.ps1 ps           # trạng thái + RAM từng service
#   .\run_bot.ps1 seed         # dump DB đang chạy -> data/db_seed/azuris.sql
#   .\run_bot.ps1 backup       # pg_dump ra file backup-YYYYMMDD-HHmm.sql
#   .\run_bot.ps1 update       # pull image mới + build + start
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Show-Help {
    Write-Host 'Usage: .\run_bot.ps1 [up|down|stop-bot|stop-infra|rebuild|restart|logs [svc]|ps|seed|backup|update]'
    Write-Host 'No args = up (build if needed + start).'
}

$cmd = 'up'
$rest = @()
$noArgs = ($args.Count -eq 0)
if ($args.Count -ge 1) {
    $cmd = "$($args[0])".ToLower()
    if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }
}

switch ($cmd) {
    'up' {
        docker compose up -d --build
        docker compose ps
        # Chuột phải > Run with PowerShell: giữ cửa sổ lại để đọc kết quả.
        if ($noArgs) { pause }
    }
    'down' { docker compose down }
    'stop-bot' { docker compose stop bot }
    'stop-infra' { docker compose stop postgres redis }
    'rebuild' { docker compose up -d --build --force-recreate }
    'restart' {
        if ($rest.Count -eq 0) { docker compose restart bot }
        else { docker compose restart $rest }
    }
    'logs' {
        $svc = 'bot'
        if ($rest.Count -ge 1) { $svc = $rest[0] }
        docker compose logs -f $svc
    }
    'ps' {
        docker compose ps
        docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'
    }
    'seed' {
        docker compose exec -T postgres pg_dump -U azuris -d azuris --no-owner --no-privileges --clean --if-exists -F p -f /tmp/seed.sql
        $ctr = (docker compose ps -q postgres).Trim()
        docker cp "${ctr}:/tmp/seed.sql" data/db_seed/azuris.sql
        Write-Host '[OK] Seed refreshed: data/db_seed/azuris.sql'
    }
    'backup' {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmm'
        $out = "backup-$stamp.sql"
        docker compose exec -T postgres pg_dump -U azuris -d azuris -F p -f /tmp/backup.sql
        $ctr = (docker compose ps -q postgres).Trim()
        docker cp "${ctr}:/tmp/backup.sql" $out
        Write-Host "[OK] Backup saved: $out"
    }
    'update' {
        docker compose pull
        docker compose up -d --build
        docker compose ps
    }
    default { Show-Help }
}
