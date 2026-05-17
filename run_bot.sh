#!/usr/bin/env bash

################################################################################
# CHAD GIBITI DISCORD BOT - UBUNTU/LINUX LAUNCHER
# Usage:
#   ./run_bot.sh
#   ./run_bot.sh --server
#   ./run_bot.sh --pm2 [--server]
#   ./run_bot.sh --pm2-fresh [--server]
#   ./run_bot.sh --preflight-only
################################################################################

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

ENABLE_SERVER=0
PM2_MODE=0
PM2_FRESH=0
PREFLIGHT_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --server)
      ENABLE_SERVER=1
      ;;
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
echo "  Chad Gibiti Discord Bot - Linux/Ubuntu Launcher"
echo "==============================================="
echo "Project root: $PROJECT_ROOT"
echo ""

echo "[INFO] Checking Python installation..."
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${RED}[ERROR]${NC} Python3 not found!"
  echo "Install Python 3.10+ first."
  exit 1
fi
echo -e "${GREEN}[OK]${NC} $(python3 --version)"
echo ""

if [ ! -d "$PROJECT_ROOT/venv" ]; then
  echo "[INFO] Creating virtual environment..."
  python3 -m venv "$PROJECT_ROOT/venv"
  echo -e "${GREEN}[OK]${NC} Virtual environment created"
else
  echo -e "${GREEN}[OK]${NC} Virtual environment exists"
fi

VENV_PY="$PROJECT_ROOT/venv/bin/python3"
if [ ! -x "$VENV_PY" ] && [ -x "$PROJECT_ROOT/venv/bin/python" ]; then
  VENV_PY="$PROJECT_ROOT/venv/bin/python"
fi
if [ ! -x "$VENV_PY" ]; then
  echo -e "${RED}[ERROR]${NC} Missing venv interpreter: $VENV_PY"
  exit 1
fi
echo -e "${GREEN}[OK]${NC} Using interpreter: $VENV_PY"
echo ""

echo "[INFO] Verifying core dependencies..."
if ! "$VENV_PY" - <<'PY' >/dev/null 2>&1
import importlib
required = ("google.genai", "discord", "dotenv", "flask", "aiohttp", "cryptography")
for mod in required:
    importlib.import_module(mod)
PY
then
  echo "[INFO] Installing/updating requirements..."
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  "$VENV_PY" -m pip install -r "$PROJECT_ROOT/requirements.txt"
  echo -e "${GREEN}[OK]${NC} Dependencies installed"
else
  echo -e "${GREEN}[OK]${NC} Dependencies already available"
fi
echo ""

if [ ! -f "$PROJECT_ROOT/.env" ]; then
  echo -e "${RED}[ERROR]${NC} .env file not found at $PROJECT_ROOT/.env"
  if [ -f "$PROJECT_ROOT/.env.example" ]; then
    echo "[INFO] You can bootstrap with:"
    echo "  cp .env.example .env"
  fi
  exit 1
fi
echo -e "${GREEN}[OK]${NC} .env file exists"

if grep -Eq '^DISCORD_TOKEN=\s*$' "$PROJECT_ROOT/.env"; then
  echo -e "${RED}[ERROR]${NC} DISCORD_TOKEN is empty in .env"
  exit 1
fi
echo -e "${GREEN}[OK]${NC} DISCORD_TOKEN configured"
echo ""

echo "[INFO] Running runtime preflight..."
"$VENV_PY" "$PROJECT_ROOT/run_bot.py" --preflight
echo -e "${GREEN}[OK]${NC} Preflight passed"
echo ""

if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
  echo "[INFO] Preflight-only mode complete."
  exit 0
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
    echo "[INFO] Running PM2 fresh cleanup..."
    pm2 update || true
    pm2 delete "$APP_NAME" || true
  fi

  export BOT_ENABLE_SERVER="$ENABLE_SERVER"
  echo "[INFO] Starting PM2 app from ecosystem file (BOT_ENABLE_SERVER=$BOT_ENABLE_SERVER)..."
  pm2 start "$ECOSYSTEM_FILE" --only "$APP_NAME" --update-env
  pm2 save

  if [ "$PM2_FRESH" -eq 1 ]; then
    echo "[INFO] If PM2 monitor shows stale pidusage errors, run:"
    echo "  pm2 update && pm2 restart $APP_NAME"
  fi

  echo -e "${GREEN}[OK]${NC} PM2 app started."
  echo "Logs: pm2 logs $APP_NAME --lines 100"
  exit 0
fi

if [ "$ENABLE_SERVER" -eq 1 ]; then
  echo "[INFO] Starting bot + server..."
  exec "$VENV_PY" "$PROJECT_ROOT/run_bot.py" --server
fi

echo "[INFO] Starting bot..."
exec "$VENV_PY" "$PROJECT_ROOT/run_bot.py"
