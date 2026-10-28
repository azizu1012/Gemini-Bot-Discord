#!/usr/bin/env bash
# Azuris Docker runner — 1 lệnh duy nhất để chạy bot TRONG Docker.
#   ./run_bot.sh                 # build (nếu cần) + start toàn stack
#   ./run_bot.sh up|down|stop-bot|stop-infra|rebuild|restart|logs [svc]|ps|seed|backup|update
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cmd="${1:-up}"
rest=("${@:2}")
noargs=0
if [ $# -eq 0 ]; then noargs=1; fi

# Dọn page-cache của Linux/VM Docker sau khi tắt — đây chính là cục "rác"
# khiến vmmemWSL phình dù container đã dừng. Chỉ đụng cache, không xóa
# image/container nào nên lần `up` sau vẫn nhanh.
drop_page_cache() {
  if command -v wsl.exe >/dev/null 2>&1; then
    wsl.exe -d docker-desktop -u root -e sh -c "sync; echo 3 > /proc/sys/vm/drop_caches" >/dev/null 2>&1 || true
  elif [ -w /proc/sys/vm/drop_caches ]; then
    sync 2>/dev/null || true
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
  fi
}

# Chạy không tham số: hiện menu thay vì start thẳng.
if [ "$noargs" -eq 1 ]; then
  echo ''
  echo '  Azuris bot — chọn thao tác:'
  echo '  [1] Start toàn stack (up)'
  echo '  [2] Chỉ tắt bot (giữ infra)'
  echo '  [3] Chỉ tắt infra (giữ container + data)'
  echo '  [4] Tắt hết (giữ data)'
  echo '  [5] Restart bot'
  echo '  [6] Xem log bot'
  echo '  [7] Trạng thái + RAM'
  echo '  [8] Build lại (rebuild)'
  echo '  [9] Seed DB từ container đang chạy'
  echo '  [10] Backup DB ra file'
  echo '  [11] Update (pull image + build + start)'
  echo '  [12] Clean sâu (down + xóa build cache + image thừa)'
  echo ''
  read -rp '  Nhập số (Enter = 1): ' pick
  pick="${pick:-1}"
  case "$pick" in
    1) cmd=up ;;
    2) cmd=stop-bot ;;
    3) cmd=stop-infra ;;
    4) cmd=down ;;
    5) cmd=restart ;;
    6) cmd=logs ;;
    7) cmd=ps ;;
    8) cmd=rebuild ;;
    9) cmd=seed ;;
    10) cmd=backup ;;
    11) cmd=update ;;
    12) cmd=clean ;;
    *) cmd=up ;;
  esac
fi

case "$cmd" in
  up)
    docker compose up -d --build
    docker image prune -f >/dev/null
    docker compose ps
    ;;
  down)
    docker compose down --remove-orphans
    docker builder prune -f >/dev/null 2>&1 || true
    drop_page_cache
    ;;
  clean)
    docker compose down --remove-orphans
    docker builder prune -af >/dev/null 2>&1 || true
    docker image prune -f >/dev/null 2>&1 || true
    drop_page_cache
    docker system df
    ;;
  stop-bot) docker compose stop bot; drop_page_cache ;;
  stop-infra) docker compose stop postgres redis; drop_page_cache ;;
  rebuild)
    docker compose up -d --build --force-recreate
    docker image prune -f >/dev/null
    ;;
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
    docker image prune -f >/dev/null
    docker compose ps
    ;;
  *) echo 'Usage: ./run_bot.sh [up|down|clean|stop-bot|stop-infra|rebuild|restart|logs [svc]|ps|seed|backup|update]'; exit 1 ;;
esac

# Giữ cửa sổ lại khi chạy không tham số (trừ logs -f vốn không bao giờ thoát).
if [ "$noargs" -eq 1 ] && [ "$cmd" != logs ]; then
  read -rp 'Nhấn Enter để đóng...'
fi
