#!/usr/bin/env python3
"""
Polymarket ↔ Kalshi Sports Arbitrage Scanner & Executor
========================================================

Usage:
    python main.py              # scan once, show opportunities
    python main.py --execute    # scan + auto-execute Polymarket leg (live)
    python main.py --loop 60    # scan every 60 seconds
    python main.py --dry-run    # always dry-run, even if AUTO_EXECUTE=true

How it works:
  1. Fetches active sports markets from Polymarket (Gamma + CLOB APIs)
  2. Fetches active sports markets from Kalshi (requires API keys in .env)
  3. Fuzzy-matches markets across platforms
  4. Checks both arb directions (YES@Poly+NO@Kalshi, NO@Poly+YES@Kalshi)
  5. Applies fee model (Poly 2% taker, Kalshi 7% on winnings, 1% slippage)
  6. If real edge ≥ 2% net after all friction → executes Polymarket leg
  7. Prints Kalshi instructions for manual execution (until keys are added)

Without Kalshi keys:
  The scanner still fetches Polymarket prices and shows you exactly
  what price you'd need on Kalshi to lock in a profitable arb.
"""
import argparse
import time
import sys
import warnings

warnings.filterwarnings("ignore")

from tabulate import tabulate

import config
from polymarket_client import fetch_sports_markets, PolyMarket
from kalshi_client import fetch_sports_markets as fetch_kalshi_markets
from market_matcher import match_markets
from arb_engine import evaluate_pair, kalshi_price_needed_for_arb, ArbOpportunity
from executor import execute_opportunity

# ANSI
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Main scan ─────────────────────────────────────────────────────────────────

def run_scan(execute: bool = False, dry_run: bool = True) -> list[ArbOpportunity]:
    """
    One full scan cycle.  Returns list of profitable opportunities found.
    """
    print(f"\n{BOLD}{'─'*65}{RESET}")
    print(f"{BOLD}  Polymarket ↔ Kalshi Arb Scanner    {time.strftime('%H:%M:%S')}{RESET}")
    print(f"{BOLD}{'─'*65}{RESET}")
    print(f"  Min edge: {config.MIN_NET_EDGE_PCT*100:.0f}%   "
          f"Max position: ${config.MAX_POSITION_USDC:.0f}   "
          f"Mode: {'LIVE' if (execute and not dry_run) else 'DRY-RUN'}")

    # ── Step 1: Fetch markets ─────────────────────────────────────────────────
    print(f"\n{CYAN}[1/4] Fetching Polymarket sports markets…{RESET}")
    poly_markets = fetch_sports_markets()
    print(f"      Found {len(poly_markets)} sports markets with sufficient liquidity.")

    print(f"\n{CYAN}[2/4] Fetching Kalshi sports markets…{RESET}")
    kalshi_markets = fetch_kalshi_markets()
    print(f"      Found {len(kalshi_markets)} Kalshi markets.")

    # ── Step 2: Match ─────────────────────────────────────────────────────────
    print(f"\n{CYAN}[3/4] Matching markets across platforms…{RESET}")
    if kalshi_markets:
        pairs = match_markets(poly_markets, kalshi_markets)
        print(f"      Matched {len(pairs)} market pairs (≥72% name similarity).")
    else:
        pairs = []
        print(f"      {YELLOW}No Kalshi markets to match — showing breakeven targets instead.{RESET}")

    # ── Step 3: Evaluate arb ──────────────────────────────────────────────────
    print(f"\n{CYAN}[4/4] Evaluating arbitrage opportunities…{RESET}")

    profitable: list[ArbOpportunity] = []

    if pairs:
        for mp in pairs:
            pm = mp.poly
            km = mp.kalshi
            opps = evaluate_pair(
                poly_yes_ask   = pm.yes_ask  if pm.yes_ask  else pm.yes_token.price + 0.01,
                poly_no_ask    = pm.no_ask   if pm.no_ask   else pm.no_token.price  + 0.01,
                kalshi_yes_ask = km.yes_ask,
                kalshi_no_ask  = km.no_ask,
                poly_market_id = pm.yes_token.token_id,   # use YES token for YES leg
                poly_title     = pm.question,
                kalshi_ticker  = km.ticker,
                kalshi_title   = km.title,
                bankroll       = config.MAX_POSITION_USDC,
            )
            for opp in opps:
                if opp.is_profitable:
                    profitable.append(opp)

    # ── Step 4: Show results ──────────────────────────────────────────────────
    _print_results(poly_markets, profitable, kalshi_markets)

    # ── Step 5: Execute ───────────────────────────────────────────────────────
    if profitable and execute:
        print(f"\n{BOLD}{'='*65}{RESET}")
        print(f"{BOLD}  EXECUTING {len(profitable)} OPPORTUNITY(IES){RESET}")
        print(f"{BOLD}{'='*65}{RESET}")
        for opp in profitable:
            execute_opportunity(opp, dry_run=dry_run)
    elif profitable and not execute:
        print(f"\n{YELLOW}  Run with --execute to place the Polymarket leg automatically.{RESET}")

    return profitable


# ── Display helpers ───────────────────────────────────────────────────────────

def _print_results(
    poly_markets: list[PolyMarket],
    profitable:   list[ArbOpportunity],
    kalshi_markets,
):
    if profitable:
        print(f"\n{GREEN}{BOLD}  ✓ {len(profitable)} PROFITABLE ARB(S) FOUND{RESET}")
        rows = []
        for opp in profitable:
            y, n = opp.yes_leg, opp.no_leg
            rows.append([
                y.market_title[:40] + "…",
                f"{y.platform[:4].upper()} YES @ {y.ask_price:.3f}",
                f"{n.platform[:4].upper()} NO  @ {n.ask_price:.3f}",
                f"{opp.gross_edge*100:.2f}¢",
                f"{opp.net_edge_pct*100:.2f}%",
                f"${opp.net_edge:.2f}",
            ])
        print(tabulate(rows,
            headers=["Market", "YES Leg", "NO Leg", "Gross", "Net%", "Profit"],
            tablefmt="rounded_outline"))
    else:
        print(f"\n  {YELLOW}No profitable arb found in this scan.{RESET}")

    # Even without arb, show what Kalshi price would be needed
    if poly_markets and not profitable:
        _print_breakeven_targets(poly_markets[:10])


def _print_breakeven_targets(poly_markets: list[PolyMarket]):
    """
    Show the max Kalshi price needed to create an arb on the top Poly markets.
    Useful when Kalshi data isn't available — lets you manually check the site.
    """
    print(f"\n{CYAN}  Polymarket prices + breakeven Kalshi targets "
          f"(for manual lookup at kalshi.com):{RESET}")

    rows = []
    for pm in poly_markets:
        y_ask = pm.yes_ask or pm.yes_token.price + 0.01
        n_ask = pm.no_ask  or pm.no_token.price  + 0.01

        # What max NO price on Kalshi allows arb if we take YES on Poly?
        be_yes = kalshi_price_needed_for_arb(y_ask, "yes")
        # What max YES price on Kalshi allows arb if we take NO on Poly?
        be_no  = kalshi_price_needed_for_arb(n_ask, "no")

        rows.append([
            pm.question[:45] + "…",
            f"{y_ask:.3f} / {n_ask:.3f}",
            f"NO ≤ {be_yes['max_kalshi_price']:.3f}",
            f"YES ≤ {be_no['max_kalshi_price']:.3f}",
            f"${pm.volume_24h:,.0f}",
        ])

    print(tabulate(rows,
        headers=["Market", "Poly YES/NO ask", "Need Kalshi NO", "Need Kalshi YES", "Vol 24h"],
        tablefmt="rounded_outline"))

    print(f"""
  {YELLOW}How to use this table:{RESET}
  • Check https://kalshi.com/markets/sports for each market.
  • If Kalshi NO price ≤ the 'Need Kalshi NO' column → arb direction 1 exists.
  • If Kalshi YES price ≤ 'Need Kalshi YES' column → arb direction 2 exists.
  • Add your Kalshi API keys to .env to automate this check.
""")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket ↔ Kalshi sports arbitrage scanner"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Execute the Polymarket leg of profitable arbs")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Simulate orders without submitting (default: True)")
    parser.add_argument("--live", action="store_true",
                        help="Actually submit orders (overrides --dry-run)")
    parser.add_argument("--loop", type=int, metavar="SECONDS",
                        help="Re-scan every N seconds (e.g. --loop 60)")
    args = parser.parse_args()

    dry_run = not args.live   # --live disables dry_run
    execute = args.execute or args.live

    if args.live and not config.AUTO_EXECUTE:
        print(f"{YELLOW}Warning: --live passed but AUTO_EXECUTE=false in .env. "
              f"Set AUTO_EXECUTE=true to submit real orders.{RESET}")

    if args.loop:
        print(f"Loop mode: scanning every {args.loop}s  (Ctrl-C to stop)")
        try:
            while True:
                run_scan(execute=execute, dry_run=dry_run)
                print(f"\n  Sleeping {args.loop}s…\n")
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n  Stopped.")
    else:
        run_scan(execute=execute, dry_run=dry_run)


if __name__ == "__main__":
    main()
