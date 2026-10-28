#!/usr/bin/env bash
# Azuris Docker runner — 1 lệnh duy nhất để chạy bot TRONG Docker.
#   ./bot.sh            # build (nếu cần) + start toàn stack
#   ./bot.sh up|down|rebuild|restart|logs [svc]|ps|seed|backup|update
# Lưu ý: đây KHÁC run_bot.sh (legacy: chạy bot trực tiếp trên máy).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cmd="${1:-up}"
rest=("${@:2}")

case "$cmd" in
  up)
    docker compose up -d --build
    docker compose ps
    ;;
  down) docker compose down ;;
  rebuild) docker compose up -d --build --force-recreate ;;
  restart)
    if [ "${#rest[@]}" -eq 0 ]; then docker compose restart bot
    else docker compose restart "${rest[@]}"; fi
    ;;
  logs)
    svc="${rest[0]:-bot}"
    docker compose logs -f "$svc"
    ;;
  ps)
    docker compose ps
    docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'
    ;;
  seed)
    docker compose exec -T postgres pg_dump -U azuris -d azuris --no-owner --no-privileges --clean --if-exists -F p -f /tmp/seed.sql
    ctr="$(docker compose ps -q postgres | tr -d '[:space:]')"
    docker cp "$ctr:/tmp/seed.sql" data/db_seed/azuris.sql
    echo '[OK] Seed refreshed: data/db_seed/azuris.sql'
    ;;
  backup)
    stamp="$(date +%Y%m%d-%H%M)"
    docker compose exec -T postgres pg_dump -U azuris -d azuris -F p -f /tmp/backup.sql
    ctr="$(docker compose ps -q postgres | tr -d '[:space:]')"
    docker cp "$ctr:/tmp/backup.sql" "backup-$stamp.sql"
    echo "[OK] Backup saved: backup-$stamp.sql"
    ;;
  update)
    docker compose pull
    docker compose up -d --build
    docker compose ps
    ;;
  *) echo 'Usage: ./bot.sh [up|down|rebuild|restart|logs [svc]|ps|seed|backup|update]'; exit 1 ;;
esac
