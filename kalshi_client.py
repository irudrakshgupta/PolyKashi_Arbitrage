"""
Kalshi client — supports both authenticated (API-key) and read-only modes.

Without API keys: fetches nothing (returns empty list) and prints a guide
on how to add keys.

With API keys: reads market data and submits orders.

Kalshi REST API v2: https://trading-api.kalshi.com/trade-api/v2
Auth: RSA-signed JWT in Authorization header.
"""
import time
import base64
import datetime
import hashlib
from dataclasses import dataclass
from typing import Optional

import requests

import config

KALSHI_URL = config.KALSHI_URL


@dataclass
class KalshiMarket:
    ticker: str
    title: str
    yes_ask: float       # price to BUY YES (0–1)
    no_ask: float        # price to BUY NO  (0–1)
    yes_bid: float
    no_bid: float
    volume: float        # total dollar volume
    open_interest: float
    close_time: str      # ISO-8601


# ── Auth helper ───────────────────────────────────────────────────────────────

def _build_auth_headers(method: str, path: str) -> dict:
    """
    Build Kalshi RSA-JWT authentication headers.
    Requires KALSHI_API_KEY_ID and a PEM key file at KALSHI_PRIVATE_KEY_PATH.
    """
    if not config.KALSHI_API_KEY_ID or not config.KALSHI_PRIVATE_KEY_PATH:
        return {}

    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        import json

        ts_ms = str(int(time.time() * 1000))
        msg   = ts_ms + method.upper() + path

        with open(config.KALSHI_PRIVATE_KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)

        signature = private_key.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA256())
        sig_b64   = base64.b64encode(signature).decode()

        return {
            "KALSHI-ACCESS-KEY":       config.KALSHI_API_KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }
    except Exception as exc:
        print(f"  [Kalshi] Auth header build failed: {exc}")
        return {}


def _has_keys() -> bool:
    return bool(config.KALSHI_API_KEY_ID and config.KALSHI_PRIVATE_KEY_PATH)


# ── Market data ───────────────────────────────────────────────────────────────

def fetch_sports_markets() -> list[KalshiMarket]:
    """
    Fetch open sports markets from Kalshi.

    Returns an empty list with a guidance message if no API keys are configured.
    """
    if not _has_keys():
        _print_no_key_guide()
        return []

    return _fetch_with_auth()


def _print_no_key_guide():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║  KALSHI API KEYS NOT CONFIGURED                                  ║
║                                                                  ║
║  To unlock live Kalshi data + order execution:                   ║
║  1. Go to https://kalshi.com/account/api-keys                    ║
║  2. Create an API key (RSA type)                                  ║
║  3. Download your private key PEM file                           ║
║  4. Add to .env:                                                  ║
║       KALSHI_API_KEY_ID=your-key-id                              ║
║       KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem                   ║
║                                                                  ║
║  The scanner will still show Polymarket prices and tell you      ║
║  exactly what price you need on Kalshi to lock in an arb.        ║
╚══════════════════════════════════════════════════════════════════╝
""")


def _fetch_with_auth() -> list[KalshiMarket]:
    """Authenticated fetch of open Kalshi sports markets."""
    path    = "/trade-api/v2/markets"
    headers = _build_auth_headers("GET", path)
    if not headers:
        return []

    sports_series = [
        "NBA", "NFL", "MLB", "NHL", "WNBA", "MLS",
        "PGA", "ATP", "WTA", "ITF", "UEFA", "FIFA",
    ]
    markets: list[KalshiMarket] = []

    for series in sports_series:
        try:
            r = requests.get(
                f"{KALSHI_URL}/markets",
                params={
                    "status": "open",
                    "series_ticker": series,
                    "limit": 200,
                },
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            print(f"  [Kalshi] Fetch error for series={series}: {exc}")
            continue

        for m in data.get("markets", []):
            ya = m.get("yes_ask")
            na = m.get("no_ask")
            if ya is None or na is None:
                continue

            # Kalshi prices come as cents (0–99 integer) or as 0–1 floats
            # Normalise to 0–1
            def norm(v):
                v = float(v)
                return v / 100 if v > 1 else v

            markets.append(KalshiMarket(
                ticker=m["ticker"],
                title=m.get("title", ""),
                yes_ask=norm(ya),
                no_ask=norm(na),
                yes_bid=norm(m.get("yes_bid", 0)),
                no_bid=norm(m.get("no_bid", 0)),
                volume=float(m.get("volume", 0)),
                open_interest=float(m.get("open_interest", 0)),
                close_time=m.get("close_time", ""),
            ))
        time.sleep(0.1)

    markets.sort(key=lambda x: x.volume, reverse=True)
    return markets


# ── Order execution ───────────────────────────────────────────────────────────

def place_order(
    ticker: str,
    side: str,           # "yes" or "no"
    price: float,        # 0–1
    size_usdc: float,    # dollar notional
    dry_run: bool = True,
) -> dict:
    """
    Place a limit resting order on Kalshi.

    Kalshi orders use *contracts* where each contract pays $1.
    contracts = size_usdc / price
    """
    if not _has_keys():
        print(f"  [Kalshi] Cannot place order — no API keys configured.")
        return {"error": "no_api_keys"}

    contracts = round(size_usdc / price, 0)
    kalshi_price_cents = round(price * 100)

    print(f"  [Kalshi order] {'DRY-RUN ' if dry_run else ''}"
          f"BUY {int(contracts)} {side.upper()} contracts "
          f"@ {kalshi_price_cents}¢  ticker={ticker}  notional=${size_usdc:.2f}")

    if dry_run:
        return {"status": "dry_run", "ticker": ticker, "side": side,
                "price": price, "contracts": contracts}

    path    = f"/trade-api/v2/markets/{ticker}/orders"
    headers = _build_auth_headers("POST", path)

    payload = {
        "action": "buy",
        "side":   side.lower(),
        "type":   "limit",
        "count":  int(contracts),
        "yes_price": kalshi_price_cents if side.lower() == "yes" else None,
        "no_price":  kalshi_price_cents if side.lower() == "no"  else None,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        r = requests.post(
            f"{KALSHI_URL}/markets/{ticker}/orders",
            json=payload,
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)}
