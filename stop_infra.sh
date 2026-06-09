#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
ENV_FILE="$PROJECT_ROOT/.env"
LOCAL_RUNTIME_ROOT_VALUE="${LOCAL_RUNTIME_ROOT:-}"
if [ -z "$LOCAL_RUNTIME_ROOT_VALUE" ] && [ -f "$ENV_FILE" ]; then
  LOCAL_RUNTIME_ROOT_VALUE="$(grep -E '^LOCAL_RUNTIME_ROOT=' "$ENV_FILE" | head -n 1 | cut -d= -f2- || true)"
fi
if [ -z "$LOCAL_RUNTIME_ROOT_VALUE" ]; then
  LOCAL_RUNTIME_ROOT_VALUE="src/.runtime"
fi

if [[ "$LOCAL_RUNTIME_ROOT_VALUE" = /* ]]; then
  RUNTIME_ROOT="$LOCAL_RUNTIME_ROOT_VALUE"
else
  RUNTIME_ROOT="$PROJECT_ROOT/$LOCAL_RUNTIME_ROOT_VALUE"
fi
export LOCAL_RUNTIME_ROOT="$LOCAL_RUNTIME_ROOT_VALUE"

RUNTIME_CONFIG_DIR="$RUNTIME_ROOT/config"
POSTGRES_DIR="$RUNTIME_ROOT/postgres"
POSTGRES_CREDENTIALS_FILE="$POSTGRES_DIR/credentials.env"
RUNTIME_RUN_DIR="$RUNTIME_ROOT/run"

REDIS_DIR="$RUNTIME_ROOT/redis"
REDIS_PID_FILE="$RUNTIME_RUN_DIR/redis.pid"
POSTGRES_PID_FILE="$RUNTIME_RUN_DIR/postgres.pid"
POSTGRES_DATA_DIR="$POSTGRES_DIR/data"

POSTGRES_PORT="${POSTGRES_PORT:-}"
REDIS_PORT="${REDIS_PORT:-6379}"

if [ -z "$POSTGRES_PORT" ] && [ -f "$POSTGRES_CREDENTIALS_FILE" ]; then
  parsed_pg_port="$(grep -E '^AZURIS_DB_PORT=[0-9]+$' "$POSTGRES_CREDENTIALS_FILE" | head -n 1 | cut -d= -f2 || true)"
  if [ -n "$parsed_pg_port" ]; then
    POSTGRES_PORT="$parsed_pg_port"
  fi
fi

if [ -z "$POSTGRES_PORT" ]; then
  POSTGRES_PORT="55432"
fi

PYTHON_BIN="$(command -v python3 || command -v python || true)"

is_port_open() {
  local host="$1"
  local port="$2"

  if [ -n "$PYTHON_BIN" ]; then
    "$PYTHON_BIN" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1.0)
try:
    sock.connect((host, port))
    print("1")
except Exception:
    print("0")
finally:
    sock.close()
PY
    return
  fi

  if command -v ss >/dev/null 2>&1; then
    if ss -ltn "( sport = :$port )" | grep -q ":$port"; then
      echo "1"
    else
      echo "0"
    fi
    return
  fi

  echo "0"
}

wait_for_port_closed() {
  local service_name="$1"
  local host="$2"
  local port="$3"
  local timeout_seconds="$4"

  for _ in $(seq 1 "$timeout_seconds"); do
    if [ "$(is_port_open "$host" "$port")" = "0" ]; then
      return 0
    fi
    sleep 1
  done

  if [ "$(is_port_open "$host" "$port")" = "0" ]; then
    return 0
  fi

  echo "[ERROR] $service_name is still listening on $host:$port"
  return 1
}

terminate_pid() {
  local pid="$1"
  local service_name="$2"

  if [ -z "$pid" ]; then
    return
  fi

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return
  fi

  echo "[INFO] Stopping $service_name PID=$pid"
  kill "$pid" >/dev/null 2>&1 || true
  for _ in $(seq 1 8); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  echo "[WARN] Escalating $service_name PID=$pid to SIGKILL"
  kill -9 "$pid" >/dev/null 2>&1 || true
  for _ in $(seq 1 5); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "[ERROR] Failed to stop $service_name PID=$pid"
    exit 1
  fi
}

stop_pid_file_process() {
  local service_name="$1"
  local pid_file="$2"

  if [ ! -f "$pid_file" ]; then
    return
  fi

  local pid
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]]; then
    terminate_pid "$pid" "$service_name"
  fi

  rm -f "$pid_file"
}

stop_runtime_postgres_processes() {
  local pids
  pids="$(ps -eo pid=,args= | awk -v marker="$POSTGRES_DIR" 'tolower($0) ~ /postgres/ && index($0, marker) > 0 {print $1}')"
  if [ -z "$pids" ]; then
    return
  fi

  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    terminate_pid "$pid" "PostgreSQL"
  done <<< "$pids"
}

stop_postgres() {
  local pg_ctl="$POSTGRES_DIR/bin/pg_ctl"

  if [ ! -x "$pg_ctl" ] || [ ! -d "$POSTGRES_DATA_DIR" ]; then
    echo "[INFO] PostgreSQL runtime not found. Skipping pg_ctl stop."
  else
    if "$pg_ctl" -D "$POSTGRES_DATA_DIR" status >/dev/null 2>&1; then
      echo "[INFO] Stopping PostgreSQL gracefully via pg_ctl..."
      "$pg_ctl" -D "$POSTGRES_DATA_DIR" stop -m fast -w -t 30 >/dev/null 2>&1 || true
    else
      echo "[INFO] PostgreSQL runtime status = not running."
    fi
  fi

  stop_pid_file_process "PostgreSQL" "$POSTGRES_PID_FILE"
  stop_runtime_postgres_processes
}

stop_redis() {
  if command -v redis-cli &>/dev/null; then
    echo "[INFO] Shutting down Redis via redis-cli..."
    redis-cli -h 127.0.0.1 -p "$REDIS_PORT" shutdown 2>/dev/null || true
  fi
  stop_pid_file_process "Redis" "$REDIS_PID_FILE"
  local redis_pids
  redis_pids="$(ps -eo pid=,args= | awk -v dir="$REDIS_DIR" 'index($0, dir) && /redis-server/ {print $1}')"
  if [ -n "$redis_pids" ]; then
    echo "[INFO] Killing remaining Redis server processes from $REDIS_DIR..."
    echo "$redis_pids" | xargs kill -9 2>/dev/null || true
  fi
}

port_owner_hint() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "( sport = :$port )" 2>/dev/null | tail -n +2 || true
    return
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -ltnp 2>/dev/null | grep ":$port" || true
    return
  fi
  echo "<owner unavailable>"
}

assert_infra_stopped() {
  local failures=0

  if ! wait_for_port_closed "PostgreSQL" "127.0.0.1" "$POSTGRES_PORT" 25; then
    echo "[ERROR] PostgreSQL port owner: $(port_owner_hint "$POSTGRES_PORT")"
    failures=$((failures + 1))
  fi

  if ! wait_for_port_closed "Redis" "127.0.0.1" "$REDIS_PORT" 25; then
    echo "[ERROR] Redis port owner: $(port_owner_hint "$REDIS_PORT")"
    failures=$((failures + 1))
  fi

  if [ "$failures" -gt 0 ]; then
    echo "[ERROR] Infra teardown failed. One or more runtime ports are still open."
    exit 1
  fi
}

echo "==============================================="
echo "  Azuris Local Infra Teardown (Linux)"
echo "==============================================="
echo "Project root: $PROJECT_ROOT"

stop_redis
stop_postgres
stop_runtime_postgres_processes

assert_infra_stopped

echo "[OK] Local Redis/PostgreSQL teardown complete."
