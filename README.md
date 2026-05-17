<div align="center">

# ⚡ PolyKalshi Arb

**A cross-platform sports prediction market arbitrage scanner & executor**

*Polymarket × Kalshi — both directions, every scan, after all fees*

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Polygon](https://img.shields.io/badge/Chain-Polygon-8247E5?style=flat-square&logo=polygon&logoColor=white)](https://polygon.technology)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![Markets](https://img.shields.io/badge/Markets-Sports-F97316?style=flat-square)]()

</div>

---

## 📐 The Core Idea

Binary prediction markets on two platforms will occasionally misprice the same real-world event. When you can buy **YES on one platform** and **NO on the other** for a combined cost under **$1.00**, you're guaranteed $1.00 back — regardless of what happens. That gap is pure edge.

```
Gross edge  =  1.00 − (P_yes + P_no)
Net edge    =  gross edge − fees − slippage
```

The bot checks **both directions** on every scan:

```
Direction 1 →  YES @ Polymarket  +  NO  @ Kalshi
Direction 2 →  NO  @ Polymarket  +  YES @ Kalshi
```

A trade is only flagged when **net edge ≥ 2%** after every friction item. No edge = no trade.

---

## 🔬 How Sizing Works

Legs are weighted so both outcomes pay out the same dollar amount — making the profit truly riskless:

```
N = Bankroll / (P_yes + P_no)

Stake_yes = N × P_yes
Stake_no  = N × P_no
```

If YES wins → you collect `N` from the YES leg.  
If NO wins → you collect `N` from the NO leg.  
Either way, you locked in a guaranteed return on day one.

---

## 💸 Fee Model

Every friction item is baked in before a trade is flagged:

| Source | Rate | Applied to |
|--------|------|------------|
| Polymarket taker fee | **2%** | Notional |
| Kalshi fee (retail) | **7%** | Winnings only |
| Slippage estimate | **1%** | Both asks |

> All constants live in `config.py` — tune them before going live.

**Hard invariant:** Before any order is placed, the code asserts that *both* outcome scenarios are profitable after fees. If either leg loses money it's a position, not an arb — and the trade is aborted.

---

## 🏗️ Architecture

```
main.py               ← CLI orchestrator (scan / loop / execute)
│
├── polymarket_client.py   ← Gamma API + CLOB price fetching + order signing
├── kalshi_client.py       ← Kalshi REST API (reads & writes, requires keys)
│
├── market_matcher.py      ← Fuzzy cross-platform name matching (rapidfuzz)
├── arb_engine.py          ← Fee math, sizing, hard-invariant assertion
├── executor.py            ← Submits Poly leg; prints Kalshi manual steps
│
├── dns_fix.py             ← ISP DNS bypass via Cloudflare DoH
└── config.py              ← All thresholds, fees, API endpoints
```

---

## 🚀 Setup

### 1 — Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/PolyKalshi_Arbitrage.git
cd PolyKalshi_Arbitrage

# Standard packages
pip install -r requirements.txt

# py-clob-client (not on PyPI — one command handles everything)
bash setup_deps.sh
```

### 2 — Configure credentials

```bash
cp .env.example .env
```

```dotenv
# Polymarket — your Polygon wallet
POLY_PRIVATE_KEY=0xYOUR_PRIVATE_KEY
POLY_ADDRESS=0xYOUR_ADDRESS

# Kalshi — from kalshi.com/account/api-keys  (RSA type)
KALSHI_API_KEY_ID=your-key-id
KALSHI_PRIVATE_KEY_PATH=/path/to/your-key.pem

# Execution
AUTO_EXECUTE=false       # true = auto-submit Polymarket leg
MAX_POSITION_USDC=50     # max $ per arb leg
MIN_NET_EDGE_PCT=0.02    # minimum net edge required
```

> ⚠️ `.env` is in `.gitignore` — it is never committed.

---

## 🖥️ Usage

```bash
# Scan once — show all opportunities (dry-run, no orders sent)
python main.py

# Continuous scan — re-check every 60 seconds
python main.py --loop 60

# Scan + auto-execute Polymarket leg on any real arb
python main.py --execute --live

# Force dry-run regardless of .env setting
python main.py --dry-run
```

### Running without Kalshi keys

No keys? No problem. The scanner still fetches live Polymarket prices and prints a **breakeven table** — the exact maximum price you can pay on Kalshi for each side and still lock in profit. Use it alongside [kalshi.com/markets/sports](https://kalshi.com/markets/sports) for manual checks.

```
╭──────────────────────────────────┬───────────────┬──────────────┬───────────────┬──────────╮
│ Market                           │ Poly YES / NO │ Need K. NO   │ Need K. YES   │ Vol 24h  │
├──────────────────────────────────┼───────────────┼──────────────┼───────────────┼──────────┤
│ Will Argentina win the World Cup │ 0.101 / 0.930 │ NO ≤ 0.850   │ YES ≤ 0.850   │ $586k    │
│ Will OKC win the NBA Finals?     │ 0.595 / 0.430 │ NO ≤ 0.356   │ YES ≤ 0.356   │ $220k    │
╰──────────────────────────────────┴───────────────┴──────────────┴───────────────┴──────────╯
```

---

## 🔒 Safety Rules

1. **Hard invariant checked before every order** — both outcomes must be profitable; a single losing scenario aborts the trade.
2. `AUTO_EXECUTE=false` by default. You opt in with `--live`.
3. Kalshi leg is printed as manual instructions until you add API keys — never one-legged exposure by default.
4. **Execution lag guard** — prices are re-validated immediately before placing leg 2. If the gap has closed since leg 1, the trade is cancelled.

---

## 📁 Project Structure

```
PolyKalshi_Arbitrage/
├── main.py                 # Entry point
├── config.py               # Fee model, thresholds, API URLs
├── polymarket_client.py    # Market data + order execution (Polymarket)
├── kalshi_client.py        # Market data + order execution (Kalshi)
├── market_matcher.py       # Cross-platform fuzzy market matching
├── arb_engine.py           # Arb math, sizing, hard invariant
├── executor.py             # Trade executor + manual Kalshi instructions
├── dns_fix.py              # Cloudflare DoH DNS override
├── setup_deps.sh           # One-command dependency installer
├── requirements.txt        # pip dependencies
└── .env.example            # Credential template
```

---

## ⚠️ Disclaimer

Prediction market arbitrage carries real risks: execution risk, counterparty risk, and regulatory risk all apply. Polymarket is restricted in certain jurisdictions — ensure you are legally permitted to trade. This project is provided for educational purposes only. Use at your own risk.

---

<div align="center">

---

*By Rudraksh P. Gupta 🛸*

</div>
