"""
Cross-platform market matcher.

Given a list of Polymarket markets and a list of Kalshi markets, returns
pairs that refer to the same real-world event with a confidence score.

Strategy:
  1. Extract a normalised "key" from each title (teams/players + date/game).
  2. Use RapidFuzz token-set-ratio to score all pairs.
  3. Return pairs above MIN_MATCH_SCORE threshold.
"""
import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from polymarket_client import PolyMarket
from kalshi_client import KalshiMarket

MIN_MATCH_SCORE = 72   # out of 100; tune based on false-positive rate


# ── Normalisation helpers ─────────────────────────────────────────────────────

_NOISE = re.compile(
    r"\b(will|the|be|in|at|on|by|to|a|an|of|for|vs\.?|against|NBA:|NFL:|MLB:|NHL:|"
    r"ATP:|WTA:|UFC:|MMA:)\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^a-z0-9 ]")


def _normalise(text: str) -> str:
    text = text.lower()
    text = _NOISE.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    # Collapse whitespace
    return re.sub(r"\s+", " ", text).strip()


# Common team-name aliases across platforms
_ALIASES: dict[str, str] = {
    "lakers":   "los angeles lakers",
    "celtics":  "boston celtics",
    "warriors": "golden state warriors",
    "heat":     "miami heat",
    "nuggets":  "denver nuggets",
    "knicks":   "new york knicks",
    "chiefs":   "kansas city chiefs",
    "eagles":   "philadelphia eagles",
    "patriots": "new england patriots",
    "yankees":  "new york yankees",
    "dodgers":  "los angeles dodgers",
    "mets":     "new york mets",
    "man city": "manchester city",
    "man utd":  "manchester united",
    "barca":    "barcelona",
}


def _expand_aliases(text: str) -> str:
    for short, full in _ALIASES.items():
        text = text.replace(short, full)
    return text


def normalise_market_title(title: str) -> str:
    n = _normalise(title)
    n = _expand_aliases(n)
    return n


# ── Match result ──────────────────────────────────────────────────────────────

@dataclass
class MarketPair:
    poly: PolyMarket
    kalshi: KalshiMarket
    score: float      # 0–100 match confidence


# ── Main matching function ────────────────────────────────────────────────────

def match_markets(
    poly_markets: list[PolyMarket],
    kalshi_markets: list[KalshiMarket],
    min_score: float = MIN_MATCH_SCORE,
) -> list[MarketPair]:
    """
    Return a list of (poly, kalshi) pairs that represent the same event.
    Sorted by match score descending.
    """
    if not poly_markets or not kalshi_markets:
        return []

    # Build normalised title index for Kalshi
    kalshi_norm   = {km: normalise_market_title(km.title) for km in kalshi_markets}
    kalshi_keys   = list(kalshi_norm.keys())
    kalshi_titles = [kalshi_norm[k] for k in kalshi_keys]

    pairs: list[MarketPair] = []
    seen: set[str] = set()   # avoid duplicate Kalshi markets in results

    for pm in poly_markets:
        poly_title = normalise_market_title(pm.question)

        # Find top 3 Kalshi candidates
        matches = process.extract(
            poly_title,
            kalshi_titles,
            scorer=fuzz.token_set_ratio,
            limit=3,
        )

        for match_text, score, idx in matches:
            if score < min_score:
                continue
            km = kalshi_keys[idx]
            # Prevent pairing the same Kalshi market to multiple Poly markets
            dedup_key = f"{pm.condition_id}:{km.ticker}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            pairs.append(MarketPair(poly=pm, kalshi=km, score=score))

    pairs.sort(key=lambda p: p.score, reverse=True)
    return pairs
