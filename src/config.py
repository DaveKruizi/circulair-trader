import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MIN_SELL_PRICE = float(os.getenv("MIN_SELL_PRICE", "15"))
MIN_NET_MARGIN = float(os.getenv("MIN_NET_MARGIN", "8"))
VINTED_COMMISSION_PCT = float(os.getenv("VINTED_COMMISSION_PCT", "5"))
SHIPPING_COST = float(os.getenv("SHIPPING_COST", "5"))
MAX_BUY_PRICE = float(os.getenv("MAX_BUY_PRICE", "50"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

# GitHub repo voor feedback/favorieten via Issues
GITHUB_REPO = os.getenv("GITHUB_REPO", "DaveKruizi/circulair-trader")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# NOTE: VINTED_COMMISSION_PCT is a placeholder (5%).
# Update once you have your Vinted Pro account and know the actual rate.
