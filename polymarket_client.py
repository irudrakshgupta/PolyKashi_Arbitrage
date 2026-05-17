"""
Polymarket CLOB client.

Read path  : public Gamma API (market metadata + prices) + CLOB order book
Write path : py-clob-client (EIP-712 signed limit orders on Polygon)

No credentials are required for market data — only for placing orders.
"""
import json
import time
import warnings
from dataclasses import dataclass
from typing import Optional

import requests

import config
from dns_fix import patched_session as _patched_session

warnings.filterwarnings("ignore")

GAMMA = config.POLY_GAMMA_URL
CLOB  = config.POLY_CLOB_URL

# Single shared session with DNS-override baked in (see dns_fix.py)
_SESSION: requests.Session = _patched_session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
})


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PolyToken:
    token_id: str
    outcome: str    # "Yes" or "No"
    price: float    # mid price (0–1)


@dataclass
class PolyMarket:
    condition_id: str
    question: str
    slug: str
    yes_token: PolyToken
    no_token:  PolyToken
    volume_24h: float
    liquidity:  float
    # Filled by _fill_book_prices() — what you actually *pay* to buy
    yes_ask: float = 0.0
    no_ask:  float = 0.0
    yes_ask_size: float = 0.0   # USDC available at best ask
    no_ask_size:  float = 0.0


# ── Market discovery ──────────────────────────────────────────────────────────

def fetch_sports_markets(
    min_volume: float   = config.MIN_VOLUME_24H,
    min_liquidity: float = config.MIN_LIQUIDITY,
) -> list[PolyMarket]:
    """
    Return open, liquid, tradeable sports markets from Polymarket.

    Filters applied:
      • Active + not closed in the Gamma API
      • Question contains a sports keyword (see config.SPORTS_KEYWORDS)
      • 24-h volume >= min_volume  AND  liquidity >= min_liquidity
      • Mid price between 0.04 and 0.96  (excludes near-resolved markets)
      • At least one side has a live ask in the CLOB order book

    Sorted by 24-h volume descending.
    """
    raw_markets: list[PolyMarket] = []
    offset = 0
    limit  = 200

    while True:
        try:
            r = _SESSION.get(
                f"{GAMMA}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit":  limit,
                    "offset": offset,
                },
                timeout=20,
            )
            r.raise_for_status()
            batch = r.json()
        except Exception as exc:
            print(f"[Polymarket] Gamma fetch error at offset={offset}: {exc}")
            break

        if not batch:
            break

        for m in batch:
            pm = _parse_market(m, min_volume, min_liquidity)
            if pm:
                raw_markets.append(pm)

        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.1)

    # Enrich with live CLOB ask prices
    tradeable: list[PolyMarket] = []
    for pm in raw_markets:
        _fill_book_prices(pm)
        # Only keep markets where BOTH sides have a live ask and the
        # book isn't stale (ask ≠ the mid+0.01 fallback on both sides)
        if pm.yes_ask > 0 and pm.no_ask > 0:
            tradeable.append(pm)
        time.sleep(0.04)

    tradeable.sort(key=lambda x: x.volume_24h, reverse=True)
    return tradeable


def _parse_market(m: dict, min_vol: float, min_liq: float) -> Optional[PolyMarket]:
    """Parse one Gamma API market dict; return None if it should be skipped."""
    question = m.get("question", "")
    if not _is_sports(question):
        return None

    vol24 = float(m.get("volume24hr", 0) or 0)
    liq   = float(m.get("liquidityNum", m.get("liquidity", 0)) or 0)
    if vol24 < min_vol or liq < min_liq:
        return None

    tokens_raw = m.get("clobTokenIds")
    outcomes   = m.get("outcomes",      '["Yes","No"]')
    prices_raw = m.get("outcomePrices", '["0.5","0.5"]')

    if isinstance(tokens_raw, str):
        tokens_raw = json.loads(tokens_raw)
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(prices_raw, str):
        prices_raw = json.loads(prices_raw)

    if not tokens_raw or len(tokens_raw) < 2:
        return None

    yes_idx, no_idx = 0, 1
    for i, o in enumerate(outcomes):
        if str(o).lower() in ("no", "n"):
            no_idx, yes_idx = i, 1 - i
            break

    yes_price = float(prices_raw[yes_idx]) if prices_raw else 0.5
    no_price  = float(prices_raw[no_idx])  if prices_raw else 0.5

    # Skip near-resolved markets — the arb math breaks down and there
    # is no real edge to capture once a market is >95% one way.
    if yes_price > 0.96 or yes_price < 0.04:
        return None

    return PolyMarket(
        condition_id=m.get("conditionId", ""),
        question=question,
        slug=m.get("slug", ""),
        yes_token=PolyToken(str(tokens_raw[yes_idx]), "Yes", yes_price),
        no_token =PolyToken(str(tokens_raw[no_idx]),  "No",  no_price),
        volume_24h=vol24,
        liquidity=liq,
    )


def _is_sports(question: str) -> bool:
    q = question.lower()
    return any(kw.lower() in q for kw in config.SPORTS_KEYWORDS)


def _fill_book_prices(pm: PolyMarket) -> None:
    """
    Fetch execution prices for both YES and NO tokens.

    Two market types on Polymarket:
    ─────────────────────────────────────────────────────────────
    STANDARD (neg_risk=False): pure CLOB, normal bid/ask.
        → Use best ask price directly.
        → Reject if ask > mid + 0.20 (stale / no real liquidity).

    NEG_RISK (neg_risk=True): multi-outcome AMM pool.
        The order book prices are inverted; the real current price
        is in `last_trade_price`.
        → Use  last_trade_price + AMM_SPREAD  as our estimated ask.
        → These markets can still be arb'd against Kalshi binary
          markets, but execution goes via Polymarket's UI or
          direct CTF Exchange interaction.
    ─────────────────────────────────────────────────────────────
    Sets ask=0.0 when the market has no usable price.
    """
    AMM_SPREAD = 0.015  # conservative 1.5% spread for neg_risk AMM fills

    for attr, token in (("yes", pm.yes_token), ("no", pm.no_token)):
        try:
            r = _SESSION.get(
                f"{CLOB}/book",
                params={"token_id": token.token_id},
                timeout=10,
            )
            r.raise_for_status()
            book = r.json()

            if book.get("neg_risk"):
                # Use last_trade_price as mid; add AMM spread for ask estimate
                ltp = book.get("last_trade_price")
                if ltp and 0.02 < float(ltp) < 0.98:
                    estimated_ask = min(round(float(ltp) + AMM_SPREAD, 4), 0.97)
                    setattr(pm, f"{attr}_ask",      estimated_ask)
                    setattr(pm, f"{attr}_ask_size", 50_000.0)   # AMM pools are deep
                else:
                    setattr(pm, f"{attr}_ask",      0.0)
                    setattr(pm, f"{attr}_ask_size", 0.0)
                continue

            # Standard CLOB market
            asks = book.get("asks", [])   # [{price, size}, …] ascending
            if not asks:
                setattr(pm, f"{attr}_ask",      0.0)
                setattr(pm, f"{attr}_ask_size", 0.0)
                continue

            best_ask      = float(asks[0]["price"])
            best_ask_size = float(asks[0]["size"])

            # Reject asks that are stale (far from mid) or out of range
            if (best_ask < 0.02 or best_ask > 0.98
                    or best_ask > token.price + 0.20):
                setattr(pm, f"{attr}_ask",      0.0)
                setattr(pm, f"{attr}_ask_size", 0.0)
            else:
                setattr(pm, f"{attr}_ask",      best_ask)
                setattr(pm, f"{attr}_ask_size", best_ask_size)

        except Exception:
            setattr(pm, f"{attr}_ask", 0.0)
            setattr(pm, f"{attr}_ask_size", 0.0)


# ── Order execution ───────────────────────────────────────────────────────────

def _get_clob_client():
    """
    Build an authenticated ClobClient using credentials from .env.
    Lazy import so the module can be used for data reading without keys.
    """
    warnings.filterwarnings("ignore")
    from py_clob_client.client import ClobClient
    from py_clob_client.constants import POLYGON

    if not config.POLY_PRIVATE_KEY or config.POLY_PRIVATE_KEY.startswith("0xYOUR"):
        raise ValueError(
            "POLY_PRIVATE_KEY not set in .env — cannot place orders."
        )

    return ClobClient(
        host=CLOB,
        chain_id=POLYGON,
        private_key=config.POLY_PRIVATE_KEY,
        signature_type=0,   # plain EOA signing
        funder=config.POLY_ADDRESS,
    )


def place_limit_order(
    token_id:  str,
    side:      str,     # "BUY"
    price:     float,   # limit price (0–1)
    size_usdc: float,   # dollar notional to spend
    dry_run:   bool = True,
) -> dict:
    """
    Place a GTC limit order on the Polymarket CLOB.

    size_usdc is in USDC (dollars).  Shares = size_usdc / price.
    With dry_run=True (default) no order is sent — use for testing.
    """
    from py_clob_client.clob_types import OrderArgs, OrderType

    shares = round(size_usdc / price, 2)
    tag    = "DRY-RUN " if dry_run else "LIVE "
    print(f"  [Poly order] {tag}{side} {shares:.2f} shares "
          f"@ {price:.4f}  token={token_id[:14]}…  notional=${size_usdc:.2f}")

    if dry_run:
        return {"status": "dry_run", "token_id": token_id,
                "price": price, "size": shares}

    client = _get_clob_client()
    try:
        try:
            client.set_api_creds(client.derive_api_key())
        except Exception:
            pass  # creds may already be set from a previous call
        signed = client.create_order(
            OrderArgs(token_id=token_id, price=price, size=shares, side=side)
        )
        return client.post_order(signed, OrderType.GTC)
    except Exception as exc:
        return {"error": str(exc)}


def get_usdc_balance() -> float:
    """Return the USDC balance of the configured wallet on Polygon."""
    try:
        client = _get_clob_client()
        bal = client.get_balance_allowance(
            params={"asset_type": "USDC", "signature_type": 0}
        )
        return float(bal.get("balance", 0))
    except Exception as exc:
        print(f"  [Poly] Balance check failed: {exc}")
        return 0.0
