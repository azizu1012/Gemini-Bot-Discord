#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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

DOWNLOADS_DIR="$RUNTIME_ROOT/downloads"
CONFIG_DIR="$RUNTIME_ROOT/config"
LOGS_DIR="$RUNTIME_ROOT/logs"
RUN_DIR="$RUNTIME_ROOT/run"

JAVA_DIR="$RUNTIME_ROOT/java"
KAFKA_DIR="$RUNTIME_ROOT/kafka"
POSTGRES_DIR="$RUNTIME_ROOT/postgres"
POSTGRES_DATA_DIR="$POSTGRES_DIR/data"
POSTGRES_LOG_FILE="$LOGS_DIR/postgres.log"
KAFKA_LOG_FILE="$LOGS_DIR/kafka.log"
POSTGRES_CREDENTIALS_FILE="$POSTGRES_DIR/credentials.env"

POSTGRES_PORT="${POSTGRES_PORT:-55432}"
KAFKA_PORT="${KAFKA_PORT:-59092}"
KAFKA_CONTROLLER_PORT="${KAFKA_CONTROLLER_PORT:-59093}"
KAFKA_CLUSTER_ID_FILE="$RUNTIME_ROOT/kafka.cluster_id"
KAFKA_CLUSTER_ID="${KAFKA_CLUSTER_ID:-AzurisLocalCluster0001}"

JAVA_DOWNLOAD_URL="${JAVA_DOWNLOAD_URL:-https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse}"
KAFKA_VERSION="${KAFKA_VERSION:-3.7.0}"
SCALA_VERSION="${SCALA_VERSION:-2.13}"
KAFKA_DOWNLOAD_URL="${KAFKA_DOWNLOAD_URL:-https://downloads.apache.org/kafka/${KAFKA_VERSION}/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz}"
POSTGRES_DOWNLOAD_URL="${POSTGRES_DOWNLOAD_URL:-https://get.enterprisedb.com/postgresql/postgresql-16.4-1-linux-x64-binaries.tar.gz}"

mkdir -p "$DOWNLOADS_DIR" "$CONFIG_DIR" "$LOGS_DIR" "$RUN_DIR"

log() {
  echo -e "${GREEN}[install_services]${NC} $1"
}

warn() {
  echo -e "${YELLOW}[install_services]${NC} $1"
}

err() {
  echo -e "${RED}[install_services]${NC} $1"
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

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "Missing required command: $1"
    exit 1
  fi
}

download_if_missing() {
  local url="$1"
  local out="$2"
  if [ -f "$out" ]; then
    log "Using cached file: $out"
    return
  fi
  log "Downloading: $url"
  curl -fL "$url" -o "$out"
}

extract_tar_to_dir() {
  local archive="$1"
  local target_parent="$2"
  local final_dir="$3"

  if [ -d "$final_dir" ]; then
    log "Already exists: $final_dir"
    return
  fi

  mkdir -p "$target_parent"
  local tmp_extract
  tmp_extract="$(mktemp -d)"
  tar -xzf "$archive" -C "$tmp_extract"

  local first_dir
  first_dir="$(find "$tmp_extract" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ -z "$first_dir" ]; then
    err "Archive did not contain a top-level directory: $archive"
    exit 1
  fi

  mv "$first_dir" "$final_dir"
  rm -rf "$tmp_extract"
}

stop_postgres_if_running() {
  local pg_ctl="$POSTGRES_DIR/bin/pg_ctl"
  if [ -x "$pg_ctl" ] && [ -d "$POSTGRES_DATA_DIR" ]; then
    "$pg_ctl" -D "$POSTGRES_DATA_DIR" status >/dev/null 2>&1 && "$pg_ctl" -D "$POSTGRES_DATA_DIR" stop -m fast >/dev/null 2>&1 || true
  fi
}

install_java() {
  if [ -x "$JAVA_DIR/bin/java" ]; then
    log "Java already installed at $JAVA_DIR"
    return
  fi

  local archive="$DOWNLOADS_DIR/java-linux-x64.tar.gz"
  download_if_missing "$JAVA_DOWNLOAD_URL" "$archive"
  extract_tar_to_dir "$archive" "$RUNTIME_ROOT" "$JAVA_DIR"
  log "Installed Java at $JAVA_DIR"
}

install_kafka() {
  if [ -x "$KAFKA_DIR/bin/kafka-server-start.sh" ]; then
    log "Kafka already installed at $KAFKA_DIR"
    return
  fi

  local archive="$DOWNLOADS_DIR/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz"
  
  if [ -f "$archive" ]; then
    log "Using cached file: $archive"
  else
    local primary_url="$KAFKA_DOWNLOAD_URL"
    local archive_url="https://archive.apache.org/dist/kafka/${KAFKA_VERSION}/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz"
    
    log "Attempting to download Kafka from primary mirror..."
    # Thử tải từ link mirror chính thức, nếu trả về lỗi (404/500) sẽ kích hoạt luồng fallback
    if curl -fL "$primary_url" -o "$archive"; then
      log "Downloaded Kafka successfully from primary mirror."
    else
      warn "Primary mirror returned error (404 or network drop). Retrying via Apache Archive..."
      rm -f "$archive" 2>/dev/null || true
      if curl -fL "$archive_url" -o "$archive"; then
        log "Downloaded Kafka successfully from Apache Archive Backup."
      else
        err "Failed to download Kafka from all available repositories."
        exit 1
      fi
    fi
  fi

  extract_tar_to_dir "$archive" "$RUNTIME_ROOT" "$KAFKA_DIR"
  log "Installed Kafka at $KAFKA_DIR"
}

  local archive="$DOWNLOADS_DIR/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz"
  download_if_missing "$KAFKA_DOWNLOAD_URL" "$archive"
  extract_tar_to_dir "$archive" "$RUNTIME_ROOT" "$KAFKA_DIR"
  log "Installed Kafka at $KAFKA_DIR"
}

install_postgres() {
  if [ -x "$POSTGRES_DIR/bin/initdb" ]; then
    log "PostgreSQL already installed at $POSTGRES_DIR"
    return
  fi

  local archive="$DOWNLOADS_DIR/postgresql-linux-x64-binaries.tar.gz"
  download_if_missing "$POSTGRES_DOWNLOAD_URL" "$archive"

  mkdir -p "$POSTGRES_DIR"
  tar -xzf "$archive" -C "$POSTGRES_DIR" --strip-components=1

  if [ ! -x "$POSTGRES_DIR/bin/initdb" ]; then
    err "PostgreSQL binaries were not extracted correctly."
    err "Set POSTGRES_DOWNLOAD_URL to a valid linux-x64 binaries tarball and rerun."
    exit 1
  fi

  log "Installed PostgreSQL at $POSTGRES_DIR"
}

init_postgres_data() {
  local initdb="$POSTGRES_DIR/bin/initdb"
  if [ -f "$POSTGRES_DATA_DIR/PG_VERSION" ]; then
    log "PostgreSQL data directory already initialized"
    return
  fi

  mkdir -p "$POSTGRES_DATA_DIR"
  "$initdb" -D "$POSTGRES_DATA_DIR" -U postgres -A trust >/dev/null
  {
    echo "listen_addresses = '127.0.0.1'"
    echo "port = $POSTGRES_PORT"
    echo "unix_socket_directories = '$RUN_DIR'"
  } >> "$POSTGRES_DATA_DIR/postgresql.conf"

  {
    echo "host all all 127.0.0.1/32 md5"
    echo "host all all ::1/128 md5"
  } >> "$POSTGRES_DATA_DIR/pg_hba.conf"

  log "Initialized PostgreSQL data directory"
}

ensure_postgres_running() {
  local pg_ctl="$POSTGRES_DIR/bin/pg_ctl"
  local psql="$POSTGRES_DIR/bin/psql"

  mkdir -p "$LOGS_DIR"
  "$pg_ctl" -D "$POSTGRES_DATA_DIR" -l "$POSTGRES_LOG_FILE" start >/dev/null || true

  for _ in $(seq 1 30); do
    if "$pg_ctl" -D "$POSTGRES_DATA_DIR" status >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  if ! "$pg_ctl" -D "$POSTGRES_DATA_DIR" status >/dev/null 2>&1; then
    err "PostgreSQL failed to start. Check: $POSTGRES_LOG_FILE"
    exit 1
  fi

  local generated_password
  generated_password="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"

  if "$psql" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='azuris'" | grep -q 1; then
    "$psql" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE azuris WITH PASSWORD '$generated_password';" >/dev/null
  else
    "$psql" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE azuris LOGIN PASSWORD '$generated_password';" >/dev/null
  fi

  if ! "$psql" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='azuris'" | grep -q 1; then
    "$psql" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE azuris OWNER azuris;" >/dev/null
  fi

  "$psql" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres -d azuris -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null

  cat > "$POSTGRES_CREDENTIALS_FILE" <<EOF
AZURIS_DB_USER=azuris
AZURIS_DB_PASSWORD=$generated_password
AZURIS_DB_NAME=azuris
AZURIS_DB_PORT=$POSTGRES_PORT
EOF
  chmod 600 "$POSTGRES_CREDENTIALS_FILE" || true

  local database_url="postgresql://azuris:${generated_password}@127.0.0.1:${POSTGRES_PORT}/azuris"
  sync_env "$database_url"
}

generate_kafka_config() {
  mkdir -p "$CONFIG_DIR/kafka" "$RUNTIME_ROOT/kafka-data"
  cat > "$CONFIG_DIR/kafka/server.properties" <<EOF
process.roles=broker,controller
node.id=1
listeners=PLAINTEXT://127.0.0.1:${KAFKA_PORT},CONTROLLER://127.0.0.1:${KAFKA_CONTROLLER_PORT}
advertised.listeners=PLAINTEXT://127.0.0.1:${KAFKA_PORT}
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
controller.quorum.voters=1@127.0.0.1:${KAFKA_CONTROLLER_PORT}
num.network.threads=3
num.io.threads=8
socket.send.buffer.bytes=102400
socket.receive.buffer.bytes=102400
socket.request.max.bytes=104857600
log.dirs=${RUNTIME_ROOT}/kafka-data
num.partitions=3
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
group.initial.rebalance.delay.ms=0
auto.create.topics.enable=true
EOF
}

ensure_kafka_running() {
  local kafka_storage="$KAFKA_DIR/bin/kafka-storage.sh"
  local kafka_start="$KAFKA_DIR/bin/kafka-server-start.sh"
  local kafka_api_versions="$KAFKA_DIR/bin/kafka-broker-api-versions.sh"

  if [ ! -f "$KAFKA_CLUSTER_ID_FILE" ]; then
    echo "$KAFKA_CLUSTER_ID" > "$KAFKA_CLUSTER_ID_FILE"
  fi

  if [ ! -f "$RUNTIME_ROOT/kafka-data/meta.properties" ]; then
    "$kafka_storage" format -t "$(cat "$KAFKA_CLUSTER_ID_FILE")" -c "$CONFIG_DIR/kafka/server.properties" >/dev/null
  fi

  if [ -f "$RUN_DIR/kafka.pid" ] && kill -0 "$(cat "$RUN_DIR/kafka.pid")" >/dev/null 2>&1; then
    log "Kafka already running"
  else
    nohup "$kafka_start" "$CONFIG_DIR/kafka/server.properties" > "$KAFKA_LOG_FILE" 2>&1 &
    echo $! > "$RUN_DIR/kafka.pid"
  fi

  for _ in $(seq 1 45); do
    if "$kafka_api_versions" --bootstrap-server "127.0.0.1:${KAFKA_PORT}" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done

  err "Kafka failed to become ready. Check: $KAFKA_LOG_FILE"
  exit 1
}

sync_env() {
  local database_url="$1"
  local kafka_bootstrap="127.0.0.1:${KAFKA_PORT}"
  local env_file="$PROJECT_ROOT/.env"

  cleanup_env_backups
  set_env_value "$env_file" "LOCAL_RUNTIME_ROOT" "$LOCAL_RUNTIME_ROOT_VALUE"
  set_env_value "$env_file" "JAVA_HOME" "$JAVA_DIR"
  set_env_value "$env_file" "KAFKA_BOOTSTRAP_SERVERS" "$kafka_bootstrap"
  set_env_value "$env_file" "DATABASE_URL" "$database_url"
  cleanup_env_backups
}

main() {
  require_cmd curl
  require_cmd tar
  require_cmd python3

  log "Project root: $PROJECT_ROOT"
  log "Runtime root: $RUNTIME_ROOT"

  stop_postgres_if_running
  install_java
  install_kafka
  install_postgres
  init_postgres_data
  ensure_postgres_running
  generate_kafka_config
  ensure_kafka_running

  log "Completed local runtime setup."
  echo "DATABASE_URL and KAFKA_BOOTSTRAP_SERVERS have been synced to .env"
  echo "PostgreSQL: 127.0.0.1:$POSTGRES_PORT"
  echo "Kafka: 127.0.0.1:$KAFKA_PORT"
}

main "$@"
