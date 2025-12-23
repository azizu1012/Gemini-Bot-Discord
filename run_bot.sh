#!/bin/bash

################################################################################
# AZURIS DISCORD BOT - UBUNTU/LINUX LAUNCHER
# Run this script to start the bot on Linux/Ubuntu servers
# Usage: ./run_bot.sh [--server]
################################################################################

set -e  # Exit on error

echo "==============================================="
echo "  Azuris Discord Bot - Linux/Ubuntu Launcher"
echo "==============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Python is installed
echo "[INFO] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Python3 not found!"
    echo "Please install Python 3.9+ first:"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-venv python3-pip"
    echo "  RHEL/CentOS: sudo yum install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}[OK]${NC} $PYTHON_VERSION"
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR]${NC} Failed to create virtual environment"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} Virtual environment created"
else
    echo -e "${GREEN}[OK]${NC} Virtual environment exists"
fi

echo ""

# Activate virtual environment
echo "[INFO] Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR]${NC} Failed to activate virtual environment"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} Virtual environment activated"
echo ""

# Check if requirements are installed
echo "[INFO] Checking dependencies..."
if ! python3 -c "import google.generativeai" 2>/dev/null; then
    echo "[INFO] Installing requirements..."
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR]${NC} Failed to install requirements"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} Dependencies installed"
else
    echo -e "${GREEN}[OK]${NC} Dependencies already installed"
fi
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${RED}[ERROR]${NC} .env file not found!"
    echo "[INFO] Creating .env from .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}[WARNING]${NC} .env created from example"
        echo "Please edit .env with your actual API keys:"
        echo ""
        echo "  nano .env"
        echo ""
        echo "Required variables:"
        echo "  - DISCORD_TOKEN"
        echo "  - GEMINI_API_KEY_1 through GEMINI_API_KEY_5"
        echo "  - Google CSE IDs and API keys"
        echo "  - Search API keys (SerpAPI, Tavily, Exa)"
        echo "  - Weather and image recognition keys"
        echo ""
        exit 1
    else
        echo "[ERROR] .env.example not found!"
        exit 1
    fi
else
    echo -e "${GREEN}[OK]${NC} .env file exists"
fi
echo ""

# Check if Discord token is configured
if grep -q "^DISCORD_TOKEN=$\|^DISCORD_TOKEN=MTQxODk0OTg4" .env 2>/dev/null; then
    echo -e "${YELLOW}[WARNING]${NC} Discord token not properly configured in .env"
    echo "Please update .env with your actual Discord bot token"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Configuration verified"
echo ""

# Parse command line arguments
if [ "$1" == "--server" ]; then
    echo "[INFO] Starting bot WITH web server..."
    echo ""
    python3 run_bot.py --server
else
    echo "[INFO] Starting bot..."
    echo ""
    python3 run_bot.py
fi
