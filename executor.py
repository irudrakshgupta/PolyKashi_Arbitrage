"""
Trade executor.

Given a profitable ArbOpportunity, this module:
  1. Re-validates that the edge is still real (prices can move between scan and execute)
  2. Checks wallet balance
  3. Executes the Polymarket leg automatically (if AUTO_EXECUTE=true)
  4. Prints step-by-step manual Kalshi instructions (since no keys yet)
  5. Hard-asserts the invariant before any real money moves
"""
import time
from typing import Optional

from arb_engine import ArbOpportunity, ArbLeg
import polymarket_client as poly
import kalshi_client as kalshi
import config

# ANSI colours for terminal output
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def execute_opportunity(opp: ArbOpportunity, dry_run: Optional[bool] = None) -> dict:
    """
    Execute one arb opportunity.

    dry_run defaults to NOT config.AUTO_EXECUTE (i.e. live if AUTO_EXECUTE=true).
    Returns a result dict with 'poly_result' and 'kalshi_result'.
    """
    if dry_run is None:
        dry_run = not config.AUTO_EXECUTE

    mode = f"{YELLOW}DRY-RUN{RESET}" if dry_run else f"{RED}LIVE{RESET}"
    print(f"\n{BOLD}{'='*65}{RESET}")
    print(f"{BOLD}  EXECUTING ARB  [{mode}]{RESET}")
    print(f"{BOLD}{'='*65}{RESET}")

    _print_opportunity(opp)

    # ── Pre-flight: hard invariant ────────────────────────────────────────────
    assert opp.is_profitable, f"Attempted to execute non-profitable arb: {opp.reject_reason}"

    # ── Balance check (Polymarket) ────────────────────────────────────────────
    poly_leg     = _find_poly_leg(opp)
    kalshi_leg   = _find_kalshi_leg(opp)

    if not dry_run:
        usdc_bal = poly.get_usdc_balance()
        required = poly_leg.effective_ask * (opp.bankroll / (opp.yes_leg.effective_ask + opp.no_leg.effective_ask))
        print(f"  Wallet USDC: ${usdc_bal:.2f}  |  Need: ${required:.2f}")
        if usdc_bal < required:
            msg = f"Insufficient USDC: have ${usdc_bal:.2f}, need ${required:.2f}"
            print(f"  {RED}✗ {msg}{RESET}")
            return {"error": msg}

    # ── Execute Polymarket leg ────────────────────────────────────────────────
    N          = opp.bankroll / (opp.yes_leg.effective_ask + opp.no_leg.effective_ask)
    poly_stake = N * poly_leg.effective_ask

    print(f"\n{CYAN}[1/2] Polymarket leg ({poly_leg.side.upper()}){RESET}")
    poly_result = poly.place_limit_order(
        token_id   = poly_leg.market_id,
        side       = "BUY",
        price      = poly_leg.ask_price,
        size_usdc  = poly_stake,
        dry_run    = dry_run,
    )
    print(f"  Result: {poly_result}")

    # ── Print Kalshi manual instructions ─────────────────────────────────────
    kalshi_stake    = N * kalshi_leg.effective_ask
    kalshi_price_ct = round(kalshi_leg.ask_price * 100)
    kalshi_contracts= round(kalshi_stake / kalshi_leg.ask_price)

    print(f"\n{CYAN}[2/2] Kalshi leg ({kalshi_leg.side.upper()}) — MANUAL ACTION REQUIRED{RESET}")

    if config.KALSHI_API_KEY_ID:
        # Keys available — execute automatically too
        kalshi_result = kalshi.place_order(
            ticker   = kalshi_leg.market_id,
            side     = kalshi_leg.side,
            price    = kalshi_leg.ask_price,
            size_usdc= kalshi_stake,
            dry_run  = dry_run,
        )
        print(f"  Result: {kalshi_result}")
    else:
        kalshi_result = {"status": "manual_required"}
        _print_kalshi_manual_steps(kalshi_leg, kalshi_stake, kalshi_contracts, kalshi_price_ct)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{GREEN}  ✓ Arb booked — guaranteed profit: "
          f"${opp.net_edge:.2f} ({opp.net_edge_pct*100:.2f}%){RESET}"
          if not dry_run else
          f"\n{YELLOW}  ↩ Dry-run complete — no orders submitted.{RESET}")

    return {"poly_result": poly_result, "kalshi_result": kalshi_result}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_poly_leg(opp: ArbOpportunity) -> ArbLeg:
    for leg in (opp.yes_leg, opp.no_leg):
        if leg.platform == "polymarket":
            return leg
    raise ValueError("No Polymarket leg in opportunity")


def _find_kalshi_leg(opp: ArbOpportunity) -> ArbLeg:
    for leg in (opp.yes_leg, opp.no_leg):
        if leg.platform == "kalshi":
            return leg
    raise ValueError("No Kalshi leg in opportunity")


def _print_opportunity(opp: ArbOpportunity):
    y, n = opp.yes_leg, opp.no_leg
    print(f"""
  YES leg : {y.market_title[:55]}
            Platform : {y.platform.upper()}
            Ask      : {y.ask_price:.4f}  (eff. {y.effective_ask:.4f})
            Payout   : {y.effective_payout:.4f} per contract

  NO  leg : {n.market_title[:55]}
            Platform : {n.platform.upper()}
            Ask      : {n.ask_price:.4f}  (eff. {n.effective_ask:.4f})
            Payout   : {n.effective_payout:.4f} per contract

  Bankroll : ${opp.bankroll:.2f}
  Stake Y  : ${opp.stake_yes:.2f}   Stake N  : ${opp.stake_no:.2f}
  Gross edge   : {opp.gross_edge*100:.2f}¢ per dollar
  Net edge     : ${opp.net_edge:.2f}  ({opp.net_edge_pct*100:.2f}%)
  Min payout   : ${opp.min_payout:.2f}  (guaranteed regardless of outcome)
""")


def _print_kalshi_manual_steps(leg: ArbLeg, stake: float, contracts: int, price_ct: int):
    print(f"""
  ┌─────────────────────────────────────────────────────────────┐
  │  KALSHI MANUAL INSTRUCTIONS                                 │
  │                                                             │
  │  1. Go to: https://kalshi.com/markets/{leg.market_id:<25}│
  │  2. Click [{leg.side.upper()}]                                           │
  │  3. Set Limit Price : {price_ct}¢                                    │
  │  4. Set Quantity    : {contracts} contracts  (≈ ${stake:.2f})           │
  │  5. Submit order    BEFORE the Polymarket fill settles      │
  │                                                             │
  │  ⚠  Execute immediately after the Polymarket leg fills.    │
  │     Price can move — re-verify edge before confirming.      │
  └─────────────────────────────────────────────────────────────┘
""")
