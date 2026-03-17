import os
from dotenv import load_dotenv

load_dotenv()

# GitHub
GITHUB_REPO = os.getenv("GITHUB_REPO", "DaveKruizi/circulair-trader")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Anthropic (optioneel — alleen voor toekomstige conditieclassificatie via Claude)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Kostentracking
MONTHLY_BUDGET_EUR = float(os.getenv("MONTHLY_BUDGET_EUR", "10.0"))
