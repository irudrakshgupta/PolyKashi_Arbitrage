# PolyKalshi Arbitrage Bot

A cross-platform sports prediction market arbitrage scanner and executor for **Polymarket** and **Kalshi**.

---

## How it works

Binary prediction markets on two platforms can sometimes misprice the same event. When you can buy **YES on Platform A** and **NO on Platform B** for a combined cost under $1.00, you lock in a guaranteed profit regardless of outcome — that's the arb.

```
Gross edge  =  1.00 − (P_yes + P_no)
Net edge    =  gross edge − Poly taker fee − Kalshi fee on winnings − slippage
```

Both directions are checked every scan:
- Direction 1: YES @ Polymarket + NO @ Kalshi  
- Direction 2: NO @ Polymarket + YES @ Kalshi

A trade is only flagged if **net edge ≥ 2%** after all friction (configurable).

---

## Fee model

| Platform   | Fee                              | Default assumption |
|------------|----------------------------------|--------------------|
| Polymarket | ~2% taker fee on notional        | `POLY_TAKER_FEE_PCT = 0.02` |
| Kalshi     | ~7% on winnings (retail tier)    | `KALSHI_FEE_ON_PROFIT_PCT = 0.07` |
| Slippage   | Estimated market impact          | `SLIPPAGE_PCT = 0.01` |

All constants live in `config.py` — adjust before going live.

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/PolyKalshi_Arbitrage.git
cd PolyKalshi_Arbitrage
pip install -r requirements.txt

# py-clob-client is not on PyPI — install from GitHub:
pip install "git+https://github.com/Polymarket/py-clob-client.git" \
            --ignore-requires-python
```

> **Note (macOS / Python 3.9):** `py-clob-client` depends on
> `poly_eip712_structs` which is also not on PyPI. Run the one-liner in
> `setup_deps.sh` to install a compatibility shim automatically.

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# Polymarket — your Polygon wallet
POLY_PRIVATE_KEY=0xYOUR_PRIVATE_KEY
POLY_ADDRESS=0xYOUR_ADDRESS

# Kalshi — from https://kalshi.com/account/api-keys (RSA type)
KALSHI_API_KEY_ID=your-key-id
KALSHI_PRIVATE_KEY_PATH=/path/to/your-key.pem

# Execution
AUTO_EXECUTE=false       # set to true to auto-submit Polymarket leg
MAX_POSITION_USDC=50     # max $ per arb leg
MIN_NET_EDGE_PCT=0.02    # minimum 2% net edge required
```

> ⚠️ **Never commit `.env`** — it's in `.gitignore`.

### 3. (Optional) ISP DNS fix

If Polymarket's domains resolve to a wrong IP on your network, the bot patches
Python's `socket.getaddrinfo` at startup to use Cloudflare's real IPs
(resolved via DNS-over-HTTPS). No config needed — it's automatic.

---

## Usage

```bash
# Scan once, show opportunities (dry-run, no orders sent)
python main.py

# Scan every 60 seconds
python main.py --loop 60

# Scan + auto-submit the Polymarket leg when arb is found
python main.py --execute --live

# Always dry-run regardless of .env setting
python main.py --dry-run
```

### Without Kalshi keys

The scanner still fetches Polymarket prices and prints a **breakeven table** —
the maximum Kalshi price you can pay on each side and still profit. Use it to
manually check [kalshi.com/markets/sports](https://kalshi.com/markets/sports).

---

## Project structure

```
main.py              — CLI entry point / scan orchestrator
config.py            — all constants, fee model, thresholds
polymarket_client.py — Gamma API + CLOB data fetching + order execution
kalshi_client.py     — Kalshi REST API (data + orders, requires keys)
market_matcher.py    — fuzzy cross-platform market name matching
arb_engine.py        — arb math, fee model, sizing, hard invariant assertion
executor.py          — trade execution + Kalshi manual instructions printer
dns_fix.py           — ISP DNS workaround (patches socket.getaddrinfo)
.env.example         — credential template (copy to .env)
```

---

## Safety rules

1. **Hard invariant**: before any order is placed, the code asserts that *both* outcome scenarios are profitable after fees. If either leg loses money, the trade is skipped — it's a position, not an arb.
2. `AUTO_EXECUTE=false` by default — you must opt in with `--live`.
3. Kalshi leg is always shown as manual instructions until you add API keys.
4. Execution lag warning: prices can move between submitting leg 1 and leg 2. The bot re-validates the edge before confirming. If the gap has closed, it aborts.

---

## Risks & disclaimers

- Prediction market arbitrage is not risk-free in practice: execution risk, counterparty risk, and regulatory risk all apply.
- Polymarket is restricted in some jurisdictions (including the US). Ensure you are legally permitted to trade.
- This code is provided as-is for educational purposes. Use at your own risk.

---

## License

MIT
