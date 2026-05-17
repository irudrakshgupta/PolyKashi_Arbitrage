"""
Central configuration for the Poly/Kalshi Arbitrage Bot.
All fee assumptions and thresholds live here — adjust before going live.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
POLY_PRIVATE_KEY   = os.getenv("POLY_PRIVATE_KEY", "")
POLY_ADDRESS       = os.getenv("POLY_ADDRESS", "")
KALSHI_API_KEY_ID  = os.getenv("KALSHI_API_KEY_ID", "")       # empty = no Kalshi auth
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

# ── API Endpoints ─────────────────────────────────────────────────────────────
POLY_CLOB_URL  = "https://clob.polymarket.com"
POLY_GAMMA_URL = "https://gamma-api.polymarket.com"
KALSHI_URL     = "https://trading-api.kalshi.com/trade-api/v2"

# ── Chain ─────────────────────────────────────────────────────────────────────
POLYGON_CHAIN_ID = 137

# ── Fee Model (conservative — err on the side of over-estimating friction) ───
# Polymarket: 2 % taker fee on the notional (charged in USDC)
POLY_TAKER_FEE_PCT    = 0.02
# Kalshi: 7 % on *winnings* (= payout minus cost). Standard retail tier.
KALSHI_FEE_ON_PROFIT_PCT = 0.07
# Estimated market-impact / slippage when lifting the ask
SLIPPAGE_PCT          = 0.01   # 1 %

# ── Arb Thresholds ────────────────────────────────────────────────────────────
MIN_NET_EDGE_PCT = float(os.getenv("MIN_NET_EDGE_PCT", "0.02"))   # 2 % minimum
MAX_POSITION_USDC = float(os.getenv("MAX_POSITION_USDC", "50"))   # $50 per leg

# ── Execution ─────────────────────────────────────────────────────────────────
AUTO_EXECUTE = os.getenv("AUTO_EXECUTE", "false").lower() == "true"

# ── Liquidity filters ─────────────────────────────────────────────────────────
MIN_VOLUME_24H  = 1_000    # min $1 k 24-h volume to bother with a market
MIN_LIQUIDITY   = 500      # min $500 on-book liquidity
MIN_BOOK_DEPTH  = 100      # min $100 available at best ask (each side)

SPORTS_KEYWORDS = [
    "NBA", "NFL", "MLB", "NHL", "WNBA", "MLS", "EPL",
    "soccer", "tennis", "golf", "UFC", "MMA",
    "Stanley Cup", "playoff", "championship", "finals",
    "World Cup", "Super Bowl", "March Madness",
    " win", " wins", " beat", "match", "game ",
    "La Liga", "Champions League", "French Open", "Wimbledon",
    "Masters", "US Open", "Australian Open",
]
