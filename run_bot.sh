#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
APP_NAME="azuris-bot"
LOG_DIR="$PROJECT_ROOT/logs"
ECOSYSTEM_FILE="$PROJECT_ROOT/ecosystem.config.js"

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

JAVA_DIR="$RUNTIME_ROOT/java"
KAFKA_DIR="$RUNTIME_ROOT/kafka"
POSTGRES_DIR="$RUNTIME_ROOT/postgres"
POSTGRES_CREDENTIALS_FILE="$POSTGRES_DIR/credentials.env"
INSTALL_SCRIPT="$PROJECT_ROOT/install_services.sh"
STOP_INFRA_SCRIPT="$PROJECT_ROOT/stop_infra.sh"
RUNTIME_CONFIG_DIR="$RUNTIME_ROOT/config"
RUNTIME_LOGS_DIR="$RUNTIME_ROOT/logs"
RUNTIME_RUN_DIR="$RUNTIME_ROOT/run"
POSTGRES_PID_FILE="$RUNTIME_RUN_DIR/postgres.pid"

POSTGRES_START_MODE="${AZURIS_POSTGRES_START_MODE:-auto}"
POSTGRES_START_MODE="$(printf '%s' "$POSTGRES_START_MODE" | tr '[:upper:]' '[:lower:]')"
if [ "$POSTGRES_START_MODE" != "auto" ] && [ "$POSTGRES_START_MODE" != "direct" ] && [ "$POSTGRES_START_MODE" != "pg_ctl" ]; then
  POSTGRES_START_MODE="auto"
fi
export AZURIS_POSTGRES_START_MODE="$POSTGRES_START_MODE"

POSTGRES_PORT="${POSTGRES_PORT:-}"
KAFKA_PORT="${KAFKA_PORT:-59092}"
ZOOKEEPER_PORT="${ZOOKEEPER_PORT:-2181}"

PM2_MODE=0
PM2_FRESH=0
PREFLIGHT_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --pm2)
      PM2_MODE=1
      ;;
    --pm2-fresh)
      PM2_MODE=1
      PM2_FRESH=1
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      ;;
  esac
done

cd "$PROJECT_ROOT"

echo "==============================================="
echo "  Azuris Discord Bot - Linux/Ubuntu Launcher"
echo "==============================================="
echo "Project root: $PROJECT_ROOT"
echo ""

VENV_PY="$PROJECT_ROOT/.venv/bin/python3"
if [ ! -x "$VENV_PY" ] && [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  VENV_PY="$PROJECT_ROOT/.venv/bin/python"
fi

if [ ! -x "$VENV_PY" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} Missing .venv interpreter and python3 not found to create it"
    exit 1
  fi

  echo "[INFO] .venv interpreter missing. Creating virtual environment at .venv..."
  python3 -m venv "$PROJECT_ROOT/.venv"
  VENV_PY="$PROJECT_ROOT/.venv/bin/python3"
  if [ ! -x "$VENV_PY" ] && [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    VENV_PY="$PROJECT_ROOT/.venv/bin/python"
  fi
fi

if [ ! -x "$VENV_PY" ]; then
  echo -e "${RED}[ERROR]${NC} Failed to create .venv interpreter"
  exit 1
fi

echo -e "${GREEN}[OK]${NC} Using interpreter: $VENV_PY"
export AZURIS_PYTHON="$VENV_PY"

auto_bootstrap_runtime() {
  local needs_bootstrap=0

  if [ ! -x "$JAVA_DIR/bin/java" ]; then
    needs_bootstrap=1
  fi
  if [ ! -x "$KAFKA_DIR/bin/kafka-server-start.sh" ]; then
    needs_bootstrap=1
  fi
  if [ ! -x "$POSTGRES_DIR/bin/initdb" ]; then
    needs_bootstrap=1
  fi
  if [ ! -f "$POSTGRES_CREDENTIALS_FILE" ]; then
    needs_bootstrap=1
  fi

  if [ "$needs_bootstrap" -eq 0 ]; then
    echo -e "${GREEN}[OK]${NC} Local runtime already exists"
    return
  fi

  echo -e "${YELLOW}[INFO]${NC} Local runtime missing. Bootstrapping via install_services.sh"
  if [ ! -x "$INSTALL_SCRIPT" ]; then
    chmod +x "$INSTALL_SCRIPT"
  fi
  "$INSTALL_SCRIPT"
}

refresh_runtime_ports_from_credentials() {
  if [ -z "$POSTGRES_PORT" ] && [ -f "$POSTGRES_CREDENTIALS_FILE" ]; then
    local parsed_pg_port
    parsed_pg_port="$(grep -E '^AZURIS_DB_PORT=[0-9]+$' "$POSTGRES_CREDENTIALS_FILE" | head -n 1 | cut -d= -f2 || true)"
    if [ -n "$parsed_pg_port" ]; then
      POSTGRES_PORT="$parsed_pg_port"
    fi
  fi

  if [ -z "$POSTGRES_PORT" ]; then
    POSTGRES_PORT="55432"
  fi
}

set_env_value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp_file=""

  touch "$env_file"
  tmp_file="$(mktemp)"

  awk -v k="$key" -v v="$value" '
    BEGIN { updated = 0 }
    index($0, k "=") == 1 {
      if (!updated) {
        print k "=" v
        updated = 1
      }
      next
    }
    { print }
    END {
      if (!updated) {
        print k "=" v
      }
    }
  ' "$env_file" > "$tmp_file"

  mv "$tmp_file" "$env_file"
}

cleanup_env_backups() {
  rm -f "$PROJECT_ROOT"/.env.bak* 2>/dev/null || true
}

sync_runtime_env() {
  local env_file="$PROJECT_ROOT/.env"
  local db_url=""

  if [ -f "$POSTGRES_CREDENTIALS_FILE" ]; then
    # shellcheck disable=SC1090
    source "$POSTGRES_CREDENTIALS_FILE"
    db_url="postgresql://${AZURIS_DB_USER}:${AZURIS_DB_PASSWORD}@127.0.0.1:${AZURIS_DB_PORT}/${AZURIS_DB_NAME}"
  fi

  cleanup_env_backups
  set_env_value "$env_file" "LOCAL_RUNTIME_ROOT" "$LOCAL_RUNTIME_ROOT_VALUE"
  set_env_value "$env_file" "JAVA_HOME" "$JAVA_DIR"
  set_env_value "$env_file" "KAFKA_BOOTSTRAP_SERVERS" "127.0.0.1:${KAFKA_PORT}"
  set_env_value "$env_file" "AZURIS_POSTGRES_START_MODE" "$POSTGRES_START_MODE"

  if [ -n "$db_url" ]; then
    set_env_value "$env_file" "DATABASE_URL" "$db_url"
  fi

  cleanup_env_backups
}

is_port_open() {
  local host="$1"
  local port="$2"
  "$VENV_PY" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1)
try:
    sock.connect((host, port))
    print("1")
except Exception:
    print("0")
finally:
    sock.close()
PY
}

wait_for_port() {
  local service_name="$1"
  local host="$2"
  local port="$3"
  local timeout_seconds="$4"

  for _ in $(seq 1 "$timeout_seconds"); do
    if [ "$(is_port_open "$host" "$port")" = "1" ]; then
      return
    fi
    sleep 1
  done

  echo -e "${RED}[ERROR]${NC} $service_name is not ready on $host:$port after ${timeout_seconds}s"
  exit 1
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

  echo -e "${RED}[ERROR]${NC} $service_name is still open on $host:$port after ${timeout_seconds}s"
  return 1
}

is_pid_file_process_running() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    echo "0"
    return
  fi

  local pid
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "1"
    return
  fi

  echo "0"
}

start_postgres_direct() {
  local postgres_bin="$POSTGRES_DIR/bin/postgres"
  local pg_data_dir="$POSTGRES_DIR/data"
  local direct_out_log="$RUNTIME_LOGS_DIR/postgres.direct.out.log"
  local direct_err_log="$RUNTIME_LOGS_DIR/postgres.direct.err.log"

  if [ ! -x "$postgres_bin" ]; then
    echo -e "${RED}[ERROR]${NC} Missing PostgreSQL binary for direct start: $postgres_bin"
    exit 1
  fi

  echo "[INFO] Starting PostgreSQL in direct mode..."
  mkdir -p "$RUNTIME_LOGS_DIR" "$RUNTIME_RUN_DIR"
  rm -f "$direct_out_log" "$direct_err_log"
  nohup "$postgres_bin" -D "$pg_data_dir" -p "$POSTGRES_PORT" >"$direct_out_log" 2>"$direct_err_log" &
  echo $! > "$POSTGRES_PID_FILE"

  wait_for_port "PostgreSQL" "127.0.0.1" "$POSTGRES_PORT" 30
}

start_postgres_if_needed() {
  local pg_ctl="$POSTGRES_DIR/bin/pg_ctl"
  local pg_data_dir="$POSTGRES_DIR/data"
  local pg_log_file="$RUNTIME_LOGS_DIR/postgres.log"
  local manual_out_log="$RUNTIME_LOGS_DIR/postgres.manual.out.log"
  local manual_err_log="$RUNTIME_LOGS_DIR/postgres.manual.err.log"

  if [ ! -d "$pg_data_dir" ]; then
    echo -e "${RED}[ERROR]${NC} Missing PostgreSQL data directory: $pg_data_dir"
    exit 1
  fi

  if [ "$(is_port_open "127.0.0.1" "$POSTGRES_PORT")" = "1" ]; then
    echo -e "${GREEN}[OK]${NC} PostgreSQL port is already open"
    return
  fi

  if [ "$POSTGRES_START_MODE" = "direct" ]; then
    start_postgres_direct
    return
  fi

  if [ ! -x "$pg_ctl" ]; then
    if [ "$POSTGRES_START_MODE" = "auto" ]; then
      echo -e "${YELLOW}[WARN]${NC} pg_ctl is missing, auto-fallback to direct mode"
      start_postgres_direct
      return
    fi
    echo -e "${RED}[ERROR]${NC} Missing PostgreSQL control binary: $pg_ctl"
    exit 1
  fi

  if "$pg_ctl" -D "$pg_data_dir" status >/dev/null 2>&1; then
    echo -e "${GREEN}[OK]${NC} PostgreSQL is already running"
    wait_for_port "PostgreSQL" "127.0.0.1" "$POSTGRES_PORT" 30
    return
  fi

  echo "[INFO] Starting PostgreSQL in background..."
  echo "[INFO] Waiting for PostgreSQL startup acknowledgement..."
  mkdir -p "$RUNTIME_LOGS_DIR"
  rm -f "$manual_out_log" "$manual_err_log"

  "$pg_ctl" -D "$pg_data_dir" -l "$pg_log_file" -w -t 30 start >"$manual_out_log" 2>"$manual_err_log" &
  local pgctl_pid=$!
  local pgctl_exit=124
  local pgctl_done=0
  for _ in $(seq 1 45); do
    if ! kill -0 "$pgctl_pid" >/dev/null 2>&1; then
      if wait "$pgctl_pid"; then
        pgctl_exit=0
      else
        pgctl_exit=$?
      fi
      pgctl_done=1
      break
    fi
    sleep 1
  done

  if [ "$pgctl_done" -eq 0 ]; then
    echo -e "${YELLOW}[WARN]${NC} pg_ctl startup check exceeded 45 seconds; terminating pg_ctl and evaluating fallback path..."
    kill -9 "$pgctl_pid" >/dev/null 2>&1 || true
  fi

  if [ "$pgctl_exit" -ne 0 ]; then
    if [ "$(is_port_open "127.0.0.1" "$POSTGRES_PORT")" = "1" ]; then
      echo -e "${YELLOW}[WARN]${NC} pg_ctl returned non-zero but PostgreSQL is reachable. Continuing startup."
      return
    fi

    if [ "$POSTGRES_START_MODE" = "auto" ]; then
      if [ "$pgctl_exit" -eq 124 ] || grep -qi "could not create restricted token" "$manual_err_log" 2>/dev/null; then
        echo -e "${YELLOW}[WARN]${NC} pg_ctl failed/timed out. Auto-fallback to direct postgres mode..."
        start_postgres_direct
        return
      fi
    fi

    echo -e "${RED}[ERROR]${NC} PostgreSQL start failed (pg_ctl exit=$pgctl_exit)"
    if [ -f "$manual_err_log" ]; then
      tail -n 30 "$manual_err_log"
    fi
    exit 1
  fi

  wait_for_port "PostgreSQL" "127.0.0.1" "$POSTGRES_PORT" 30
}

is_kafka_kraft_mode() {
  local kafka_config="$RUNTIME_CONFIG_DIR/kafka/server.properties"
  if [ ! -f "$kafka_config" ]; then
    echo "0"
    return
  fi

  if grep -Eq '^\s*process\.roles\s*=' "$kafka_config" || grep -Eq '^\s*controller\.quorum\.voters\s*=' "$kafka_config"; then
    echo "1"
    return
  fi

  echo "0"
}

get_zookeeper_client_port() {
  local zk_config="$KAFKA_DIR/config/zookeeper.properties"
  if [ -f "$zk_config" ]; then
    local line
    line="$(grep -E '^\s*clientPort\s*=\s*[0-9]+\s*$' "$zk_config" | head -n 1 || true)"
    if [ -n "$line" ]; then
      echo "$line" | sed -E 's/^\s*clientPort\s*=\s*([0-9]+)\s*$/\1/'
      return
    fi
  fi

  echo "$ZOOKEEPER_PORT"
}

collect_infra_active_reasons() {
  local reasons=()

  if [ "$(is_pid_file_process_running "$RUNTIME_RUN_DIR/kafka.pid")" = "1" ]; then
    reasons+=("Kafka PID file points to a running process")
  fi
  if [ "$(is_pid_file_process_running "$RUNTIME_RUN_DIR/zookeeper.pid")" = "1" ]; then
    reasons+=("Zookeeper PID file points to a running process")
  fi
  if [ "$(is_pid_file_process_running "$POSTGRES_PID_FILE")" = "1" ]; then
    reasons+=("PostgreSQL PID file points to a running process")
  fi

  if [ "${#reasons[@]}" -eq 0 ]; then
    return
  fi

  printf '%s\n' "${reasons[@]}"
}

auto_reset_infra_if_needed() {
  local reasons
  reasons="$(collect_infra_active_reasons)"
  if [ -z "$reasons" ]; then
    echo -e "${GREEN}[OK]${NC} No running local infra detected before startup"
    return
  fi

  echo -e "${YELLOW}[WARN]${NC} Existing local infra detected. Running stop_infra.sh before startup..."
  while IFS= read -r reason; do
    [ -n "$reason" ] || continue
    echo "  - $reason"
  done <<< "$reasons"

  if [ ! -f "$STOP_INFRA_SCRIPT" ]; then
    echo -e "${RED}[ERROR]${NC} Missing stop script: $STOP_INFRA_SCRIPT"
    exit 1
  fi

  if [ ! -x "$STOP_INFRA_SCRIPT" ]; then
    chmod +x "$STOP_INFRA_SCRIPT"
  fi

  if ! "$STOP_INFRA_SCRIPT"; then
    echo -e "${RED}[ERROR]${NC} stop_infra.sh failed"
    exit 1
  fi

  local zookeeper_client_port
  zookeeper_client_port="$(get_zookeeper_client_port)"

  if ! wait_for_port_closed "PostgreSQL" "127.0.0.1" "$POSTGRES_PORT" 25; then
    exit 1
  fi
  if ! wait_for_port_closed "Kafka" "127.0.0.1" "$KAFKA_PORT" 25; then
    exit 1
  fi
  if [ "$(is_kafka_kraft_mode)" = "0" ] && ! wait_for_port_closed "Zookeeper" "127.0.0.1" "$zookeeper_client_port" 25; then
    exit 1
  fi

  echo -e "${GREEN}[OK]${NC} Existing local infra was stopped successfully"
}

start_zookeeper_if_needed() {
  if [ "$(is_kafka_kraft_mode)" = "1" ]; then
    echo "[INFO] Kafka is running in KRaft mode. Skipping Zookeeper startup."
    return
  fi

  local zk_start="$KAFKA_DIR/bin/zookeeper-server-start.sh"
  local zk_config="$KAFKA_DIR/config/zookeeper.properties"
  local zk_pid_file="$RUNTIME_RUN_DIR/zookeeper.pid"
  local zk_log_file="$RUNTIME_LOGS_DIR/zookeeper.log"
  local zk_err_log_file="$RUNTIME_LOGS_DIR/zookeeper.err.log"
  local zk_client_port
  zk_client_port="$(get_zookeeper_client_port)"

  if [ ! -x "$zk_start" ] || [ ! -f "$zk_config" ]; then
    echo -e "${RED}[ERROR]${NC} Kafka không chạy KRaft nhưng thiếu script/config Zookeeper"
    exit 1
  fi

  if [ "$(is_port_open "127.0.0.1" "$zk_client_port")" = "1" ]; then
    echo -e "${GREEN}[OK]${NC} Zookeeper is already running on port $zk_client_port"
    return
  fi

  echo "[INFO] Starting Zookeeper in background..."
  mkdir -p "$RUNTIME_RUN_DIR" "$RUNTIME_LOGS_DIR"
  nohup "$zk_start" "$zk_config" > "$zk_log_file" 2> "$zk_err_log_file" &
  echo $! > "$zk_pid_file"

  wait_for_port "Zookeeper" "127.0.0.1" "$zk_client_port" 45
}

start_kafka_if_needed() {
  local kafka_start="$KAFKA_DIR/bin/kafka-server-start.sh"
  local kafka_config="$RUNTIME_CONFIG_DIR/kafka/server.properties"
  local kafka_pid_file="$RUNTIME_RUN_DIR/kafka.pid"
  local kafka_log_file="$RUNTIME_LOGS_DIR/kafka.log"

  if [ ! -x "$kafka_start" ]; then
    echo -e "${RED}[ERROR]${NC} Missing Kafka start script: $kafka_start"
    exit 1
  fi

  if [ ! -f "$kafka_config" ]; then
    echo -e "${RED}[ERROR]${NC} Missing Kafka config: $kafka_config"
    exit 1
  fi

  if [ "$(is_port_open "127.0.0.1" "$KAFKA_PORT")" = "1" ]; then
    echo -e "${GREEN}[OK]${NC} Kafka is already running"
    return
  fi

  echo "[INFO] Starting Kafka in background..."
  mkdir -p "$RUNTIME_RUN_DIR" "$RUNTIME_LOGS_DIR"
  export JAVA_HOME="$JAVA_DIR"
  nohup "$kafka_start" "$kafka_config" > "$kafka_log_file" 2>&1 &
  echo $! > "$kafka_pid_file"

  wait_for_port "Kafka" "127.0.0.1" "$KAFKA_PORT" 60
}

start_local_infra() {
  start_postgres_if_needed
  start_zookeeper_if_needed
  start_kafka_if_needed
}

auto_bootstrap_runtime
refresh_runtime_ports_from_credentials
auto_reset_infra_if_needed
sync_runtime_env
start_local_infra

export JAVA_HOME="$JAVA_DIR"
export PATH="$JAVA_HOME/bin:$POSTGRES_DIR/bin:$PATH"

echo "[INFO] Verifying core dependencies..."
if ! "$VENV_PY" - <<'PY' >/dev/null 2>&1
import importlib
required = ("google.genai", "discord", "dotenv", "flask", "aiohttp", "cryptography", "openai", "asyncpg", "aiokafka")
for mod in required:
    importlib.import_module(mod)
PY
then
  echo "[INFO] Installing/updating requirements..."
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  "$VENV_PY" -m pip install -r "$PROJECT_ROOT/requirements.txt"
fi

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo -e "${RED}[ERROR]${NC} .env is missing even after runtime sync"
  exit 1
fi

echo "[INFO] Running runtime preflight..."
"$VENV_PY" "$PROJECT_ROOT/run_bot.py" --preflight
echo -e "${GREEN}[OK]${NC} Preflight passed"

if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
  echo "[INFO] Preflight-only mode complete."
  exit 0
fi

if ! grep -Eq '^DISCORD_TOKEN=.+$' "$PROJECT_ROOT/.env"; then
  echo -e "${RED}[ERROR]${NC} DISCORD_TOKEN is missing in .env"
  echo "Please set your real token, then rerun."
  exit 1
fi

mkdir -p "$LOG_DIR"

if [ "$PM2_MODE" -eq 1 ]; then
  if ! command -v pm2 >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} pm2 not found. Install with: npm i -g pm2"
    exit 1
  fi

  if [ ! -f "$ECOSYSTEM_FILE" ]; then
    echo -e "${RED}[ERROR]${NC} Missing $ECOSYSTEM_FILE"
    exit 1
  fi

  if [ "$PM2_FRESH" -eq 1 ]; then
    pm2 update || true
    pm2 delete "$APP_NAME" || true
  fi

  pm2 start "$ECOSYSTEM_FILE" --only "$APP_NAME" --update-env
  pm2 save
  echo -e "${GREEN}[OK]${NC} PM2 app started"
  exit 0
fi

exec "$VENV_PY" "$PROJECT_ROOT/run_bot.py"
