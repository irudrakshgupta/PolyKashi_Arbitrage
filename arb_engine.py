"""
Arbitrage engine.

Cross-platform arb mechanics:
  - Buy YES on platform A  (ask price = p_ya)
  - Buy NO  on platform B  (ask price = p_nb)
  - Combined cost = p_ya + p_nb  (< $1 → raw arb exists)
  - One leg always wins $1; the other expires at $0.
  - After fees the guaranteed return must still exceed combined cost.

Both directions are checked:
  Direction 1: YES @ Polymarket + NO  @ Kalshi
  Direction 2: NO  @ Polymarket + YES @ Kalshi

Sizing (equal-payout allocation):
  Buy N shares of each side.  N contracts cost N*p each.
  For a given dollar bankroll B:
      N = B / (p_yes + p_no)
      Stake_yes = N * p_yes
      Stake_no  = N * p_no
  This ensures: if YES wins → win N dollars; if NO wins → win N dollars.
  (Before fees.)

Effective payouts after fees:
  Polymarket leg wins:
      eff = 1.0 * (1 - POLY_TAKER_FEE_PCT)            ← fee on notional
  Kalshi leg wins:
      eff = 1.0 - KALSHI_FEE_ON_PROFIT_PCT * (1 - price)  ← fee on profit only

Hard invariant (asserted before any execution):
      eff_payout_yes + eff_payout_no  MUST be > total_cost_per_N

Decision rule:
      net_edge_pct ≥ MIN_NET_EDGE_PCT   →  trade
"""
from dataclasses import dataclass, field
from typing import Literal

import config

POLY_FEE   = config.POLY_TAKER_FEE_PCT
KALSHI_FEE = config.KALSHI_FEE_ON_PROFIT_PCT
SLIP       = config.SLIPPAGE_PCT


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ArbLeg:
    platform: Literal["polymarket", "kalshi"]
    side: Literal["yes", "no"]
    market_id: str          # condition_id (Poly) or ticker (Kalshi)
    market_title: str
    ask_price: float        # raw best-ask (0–1)
    effective_ask: float    # ask * (1 + slippage)
    effective_payout: float # net $1 payout after platform fees


@dataclass
class ArbOpportunity:
    yes_leg: ArbLeg
    no_leg:  ArbLeg
    bankroll: float         # total dollars deployed

    # Filled by calculate()
    gross_edge: float       = 0.0   # 1 - (p_yes + p_no)  [before fees]
    net_edge:   float       = 0.0   # guaranteed profit in dollars
    net_edge_pct: float     = 0.0   # net_edge / bankroll
    stake_yes:  float       = 0.0   # dollars on yes leg
    stake_no:   float       = 0.0   # dollars on no leg
    min_payout: float       = 0.0   # minimum guaranteed return
    is_profitable: bool     = False
    reject_reason: str      = ""

    def calculate(self) -> "ArbOpportunity":
        p_y   = self.yes_leg.effective_ask
        p_n   = self.no_leg.effective_ask
        eff_y = self.yes_leg.effective_payout
        eff_n = self.no_leg.effective_payout

        total_cost_ratio = p_y + p_n          # cost per 1 unit of payout

        # For bankroll B: buy B/(p_y+p_n) contracts of each side
        N = self.bankroll / total_cost_ratio
        self.stake_yes = N * p_y
        self.stake_no  = N * p_n

        # Payouts (per contract × N contracts, then apply platform fee factor)
        payout_if_yes = N * eff_y
        payout_if_no  = N * eff_n

        self.min_payout   = min(payout_if_yes, payout_if_no)
        self.gross_edge   = 1.0 - total_cost_ratio
        self.net_edge     = self.min_payout - self.bankroll
        self.net_edge_pct = self.net_edge / self.bankroll if self.bankroll else 0.0

        # ── Hard invariant ────────────────────────────────────────────────────
        # After all costs, BOTH outcome scenarios must be in the black.
        # If even ONE outcome loses money this is NOT an arb — it's a position.
        if payout_if_yes <= self.bankroll:
            self.reject_reason = (
                f"YES scenario loses: payout ${payout_if_yes:.2f} < bankroll ${self.bankroll:.2f}"
            )
            self.is_profitable = False
            return self

        if payout_if_no <= self.bankroll:
            self.reject_reason = (
                f"NO scenario loses: payout ${payout_if_no:.2f} < bankroll ${self.bankroll:.2f}"
            )
            self.is_profitable = False
            return self

        if self.net_edge_pct < config.MIN_NET_EDGE_PCT:
            self.reject_reason = (
                f"Edge {self.net_edge_pct*100:.2f}% < minimum {config.MIN_NET_EDGE_PCT*100:.0f}%"
            )
            self.is_profitable = False
            return self

        self.is_profitable = True
        return self


# ── Core factory ──────────────────────────────────────────────────────────────

def _make_leg(
    platform: str,
    side: str,
    market_id: str,
    market_title: str,
    raw_ask: float,
) -> ArbLeg:
    """Construct an ArbLeg, computing effective ask and effective payout."""
    effective_ask = raw_ask * (1 + SLIP)

    if platform == "polymarket":
        # Poly charges ~2% of notional on taker fills
        effective_payout = 1.0 * (1.0 - POLY_FEE)
    else:
        # Kalshi charges 7% of *winnings* = 7% × (1 - cost)
        effective_payout = 1.0 - KALSHI_FEE * (1.0 - raw_ask)

    return ArbLeg(
        platform=platform,
        side=side,
        market_id=market_id,
        market_title=market_title,
        ask_price=raw_ask,
        effective_ask=effective_ask,
        effective_payout=effective_payout,
    )


def evaluate_pair(
    poly_yes_ask: float,
    poly_no_ask: float,
    kalshi_yes_ask: float,
    kalshi_no_ask: float,
    poly_market_id: str,
    poly_title: str,
    kalshi_ticker: str,
    kalshi_title: str,
    bankroll: float = config.MAX_POSITION_USDC,
) -> list[ArbOpportunity]:
    """
    Evaluate BOTH arb directions for a matched market pair.

    Returns a list of ArbOpportunity objects (0, 1, or 2 items),
    one per direction.  Caller should filter for .is_profitable.
    """
    opportunities: list[ArbOpportunity] = []

    # Direction 1 : YES @ Poly + NO @ Kalshi
    d1 = ArbOpportunity(
        yes_leg=_make_leg("polymarket", "yes", poly_market_id,
                          poly_title, poly_yes_ask),
        no_leg =_make_leg("kalshi",     "no",  kalshi_ticker,
                          kalshi_title, kalshi_no_ask),
        bankroll=bankroll,
    ).calculate()
    opportunities.append(d1)

    # Direction 2 : NO @ Poly + YES @ Kalshi
    d2 = ArbOpportunity(
        yes_leg=_make_leg("kalshi",     "yes", kalshi_ticker,
                          kalshi_title, kalshi_yes_ask),
        no_leg =_make_leg("polymarket", "no",  poly_market_id,
                          poly_title, poly_no_ask),
        bankroll=bankroll,
    ).calculate()
    opportunities.append(d2)

    return opportunities


# ── Breakeven helper (used when Kalshi data unavailable) ─────────────────────

def kalshi_price_needed_for_arb(
    poly_ask: float,
    poly_side: Literal["yes", "no"],
    bankroll: float = config.MAX_POSITION_USDC,
) -> dict:
    """
    Given that we'll take `poly_side` on Polymarket at `poly_ask`,
    compute the maximum price we can pay on Kalshi for the *opposite* side
    such that an arb still exists after fees.

    Returns a dict with 'max_kalshi_price' and 'gross_edge_at_max'.
    """
    poly_eff_ask    = poly_ask * (1 + SLIP)
    poly_eff_payout = 1.0 * (1.0 - POLY_FEE)

    # We need: min(poly_eff_payout, kalshi_eff_payout) > poly_eff_ask + kalshi_eff_ask
    # Binding constraint: kalshi_eff_payout > total_cost_per_contract AND
    #                     poly_eff_payout > total_cost_per_contract
    # With minimum edge: net_edge_pct = (min_payout - bankroll) / bankroll >= MIN_NET_EDGE_PCT
    # Solve for kalshi_ask:
    #   total_cost_per_contract = poly_eff_ask + k_eff_ask
    #   We need total_cost < min_payout_factor - MIN_NET_EDGE_PCT buffer
    # Simplified: poly_eff_ask + kalshi_ask*(1+SLIP) < poly_eff_payout / (1 + MIN_NET_EDGE_PCT)

    max_total_cost  = poly_eff_payout / (1.0 + config.MIN_NET_EDGE_PCT)
    max_kalshi_ask  = (max_total_cost - poly_eff_ask) / (1.0 + SLIP)
    gross_at_max    = 1.0 - (poly_eff_ask + max_kalshi_ask * (1 + SLIP))

    return {
        "poly_side":          poly_side,
        "poly_ask":           poly_ask,
        "max_kalshi_price":   max(0.0, round(max_kalshi_ask, 4)),
        "gross_edge_at_max":  round(gross_at_max, 4),
    }
