#!/bin/bash
# Circulair Trader — Setup script

set -e

echo "=== Circulair Trader Setup ==="

# 1. Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Install Playwright browsers (for JS-rendered sites if needed later)
# playwright install chromium

# 4. Copy env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  .env aangemaakt. Voeg je ANTHROPIC_API_KEY toe aan .env!"
fi

# 5. Create output directory
mkdir -p output logs

echo ""
echo "✅ Setup klaar!"
echo ""
echo "Volgende stappen:"
echo "  1. Voeg je ANTHROPIC_API_KEY toe aan .env"
echo "  2. Update VINTED_COMMISSION_PCT in .env zodra je je Vinted Pro tarief weet"
echo "  3. Test met: python src/main.py --dry-run"
echo "  4. Volledige run: python src/main.py"
echo "  5. Dashboard bekijken: open output/index.html"
echo ""
echo "MCP server starten (voor Claude Desktop):"
echo "  python src/mcp_server.py"
