#!/usr/bin/env python3
"""
Investment Tracker — Alpa Parag Gandhi | Bank of Singapore
========================================================
Tracks FCNs, AT1 bonds, and accumulators with live prices.

Usage:
  python investment_tracker.py

To add a received coupon, add an entry to the 'coupons_received' list
in the relevant position:
  {"date": "2026-07-17", "amount_usd": 1938.75, "note": "Period 1"}

To fill in a missing FCN (Semiconductor FCN), replace the None values
with the actual figures from the term sheet.
"""

import subprocess, sys, json, webbrowser, threading, time, os
from datetime import datetime, date
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Auto-install yfinance ─────────────────────────────────────────────────────
try:
    import yfinance as yf
except ImportError:
    print("📦 Installing yfinance...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance",
                           "--break-system-packages", "-q"])
    import yfinance as yf

# ═════════════════════════════════════════════════════════════════════════════
#  PORTFOLIO CONFIGURATION  ← Edit this section to match your positions
# ═════════════════════════════════════════════════════════════════════════════

OWNER  = "Alpa Parag Gandhi"
BANK   = "Bank of Singapore"
AUDUSD = 0.6986  # AUD → USD rate (updated 15 Jul 2026 from BOS ad-hoc statement)

# ─── Cash / Transfers ────────────────────────────────────────────────────────
# All inward SWIFT transfers to BOS account 1000400774-1 (as of 22 Jun 2026)
CASH_TRANSFERS = [
    {"date": "07 MAY 26", "amount_usd": 130_000.00},
    {"date": "08 MAY 26", "amount_usd": 129_990.00},
    {"date": "08 MAY 26", "amount_usd": 129_990.00},
    {"date": "20 MAY 26", "amount_usd": 130_000.00},
    {"date": "21 MAY 26", "amount_usd": 130_000.00},
    {"date": "21 MAY 26", "amount_usd": 129_990.00},
    {"date": "22 MAY 26", "amount_usd": 129_990.00},
    {"date": "26 MAY 26", "amount_usd": 129_990.00},
    {"date": "05 JUN 26", "amount_usd": 130_000.00},
    {"date": "05 JUN 26", "amount_usd": 129_990.00},
    {"date": "05 JUN 26", "amount_usd": 129_990.00},
    {"date": "08 JUN 26", "amount_usd": 130_000.00},
    {"date": "11 JUN 26", "amount_usd": 130_000.00},
    {"date": "12 JUN 26", "amount_usd": 129_990.00},
    {"date": "12 JUN 26", "amount_usd": 129_990.00},
    {"date": "24 JUN 26", "amount_usd": 130_000.00},   # FT26175K06N8
]
TOTAL_CASH_DEPOSITED = sum(t["amount_usd"] for t in CASH_TRANSFERS)  # $2,079,910

# ─── Cash Balance ─────────────────────────────────────────────────────────────
# HOW TO MAINTAIN:
#   1. When you get a new BOS statement → update CASH_BALANCE_BOS + CASH_BALANCE_DATE
#      and clear TRADES_SINCE_STATEMENT (it's now baked into the new BOS number).
#   2. When you add a new trade to the tracker → also add it to TRADES_SINCE_STATEMENT.
#      The tracker auto-deducts it from the available cash.
#   3. New SWIFT deposits after the statement → add to CASH_TRANSFERS and also add a
#      positive entry in TRADES_SINCE_STATEMENT (or just wait for next BOS statement).
#
# Available cash = CASH_BALANCE_BOS - sum(TRADES_SINCE_STATEMENT costs)
# Accumulators are NOT listed here — they're a forward equity delivery, not a cash debit.

# ─── Dashboard Password (HTTP Basic Auth) ────────────────────────────────────
# Change these to whatever you like. Anyone visiting the Render URL will be
# prompted for username + password before they can see the dashboard.
DASHBOARD_USER     = "alpa"
DASHBOARD_PASSWORD = "invest2026"

CASH_BALANCE_BOS    = 214_950.33
CASH_BALANCE_DATE   = "15 Jul 2026"   # BOS ad-hoc statement (generated 16 Jul 2026 16:27)
# Note: $214,950.33 already includes both pending debits:
#   − $150,000 Nomura AMZN/ORCL FCN settlement (value date 16 Jul 2026)
#   − $100,000 OCBC TMO/JNJ/LLY FCN settlement (value date 22 Jul 2026)

# New trades / deposits since the last BOS statement.
# cost_usd: positive = cash in (deposit/dividend), negative = cash out (purchase).
TRADES_SINCE_STATEMENT = [
    # All activity through 15 Jul 2026 (incl. pending FCN settlements) is baked
    # into $214,950.33 above. Items below are all post-15-Jul-2026.
    # OCBC TMO/JNJ/LLY FCN settlement (22 Jul 2026, $100k) already in the balance.
    {"date": "20 Jul 26", "description": "SCB Banks FCN coupon — Period 1 (gs_jpm_ms, DIARSC2619685568)", "cost_usd": +1_791.60},
    {"date": "20 Jul 26", "description": "HSBC Industrials FCN coupon — Period 1 (hon_su_sie, DIARSC2619697304)", "cost_usd": +1_014.17},
    {"date": "20 Jul 26", "description": "QQQ accumulator delivery — 10 sh @ strike $573.977 (SCTRSC2620257535)", "cost_usd": -5_739.77},
    {"date": "20 Jul 26", "description": "MS Roundhill DRAM Memory ETF FCN — $100,000 (XS3427736569, settles 03 Aug 2026)", "cost_usd": -100_000.00},
    {"date": "21 Jul 26", "description": "MS Asia ETF FCN coupon — Period 1 (ms_asia_etf, DIARSC2619772044)", "cost_usd": +1_938.75},
]
CASH_SINCE_STATEMENT = sum(t["cost_usd"] for t in TRADES_SINCE_STATEMENT)

# ─── Known Accumulator KO Events ─────────────────────────────────────────────
# Add an entry here whenever an accumulator is knocked out.
# This is the source of truth for Render (no persistent filesystem there).
# The local file-based KO log merges with this at runtime.
KNOWN_KO_EVENTS = {
    "googl_accumulator": {
        "ko_date":          "2026-06-20",
        "ko_price":         368.03,
        "ticker":           "GOOGL",
        "knockout_barrier": 367.0611,
    },
    "googl_accumulator_2": {
        "ko_date":          "2026-06-29",
        "ko_price":         353.65,
        "ticker":           "GOOGL",
        "knockout_barrier": 352.7647,
    },
    "lly_accumulator": {
        "ko_date":          "2026-06-24",
        "ko_price":         1208.12,
        "ticker":           "LLY",
        "knockout_barrier": 1143.30,
    },
    "meta_accumulator": {
        "ko_date":          "2026-07-01",
        "ko_price":         612.91,
        "ticker":           "META",
        "knockout_barrier": 590.0458,
    },
}

# ─── FCN Positions ────────────────────────────────────────────────────────────
# currency field on underlyings: "USD" (default), "GBP", "EUR", "CHF"
# For non-USD tickers, Yahoo Finance returns local-currency prices — barriers
# are stored in the same local currency, so % comparisons stay valid.

FCN_POSITIONS = [

    # ── 1. US Index Worst-of FCN — SPY / QQQ / DIA  (BNP Paribas, XS3358849498) ─
    {
        "id": "spy_qqq_dia",
        "name": "US Index Worst-of FCN",
        "issuer": "BNP Paribas (ISIN: XS3358849498)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 0.77,
        "coupon_annual_pct": 9.24,
        "issue_date": "2026-05-13",
        "maturity_date": "2027-06-01",
        "first_autocall_date": "2026-08-27",
        "autocall_freq": "Monthly",
        "ki_type": "European — KI at 80%, Strike at 90%; checked only at Determination Date (27 May 2027)",
        "underlyings": [
            {"ticker": "SPY", "name": "SPDR S&P 500 ETF",  "initial": 738.37, "ki_pct": 80, "strike_pct": 90, "ac_pct": 100},
            {"ticker": "QQQ", "name": "Invesco QQQ Trust",  "initial": 709.75, "ki_pct": 80, "strike_pct": 90, "ac_pct": 100},
            {"ticker": "DIA", "name": "SPDR Dow Jones ETF", "initial": 496.29, "ki_pct": 80, "strike_pct": 90, "ac_pct": 100},
        ],
        "coupons_received": [
            {"date": "2026-07-01", "amount_usd": 770.00, "note": "Period 1 — confirmed BOS transaction report 3 Jul 2026"},
        ],
    },

    # ── 2. US Tech Worst-of FCN — META / GOOGL / NVDA  (HSBC, XS3288762993) ──
    {
        "id": "meta_googl_nvda",
        "name": "US Tech Worst-of FCN",
        "issuer": "HSBC (ISIN: XS3288762993)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 1.0833,
        "coupon_annual_pct": 13.0,
        "issue_date": "2026-05-13",
        "maturity_date": "2027-06-02",
        "first_autocall_date": "2026-08-28",
        "autocall_freq": "Monthly",
        "ki_type": "European — KI checked only at Final Valuation Date (28 May 2027)",
        "underlyings": [
            {"ticker": "META",  "name": "Meta Platforms",     "initial": 598.83, "ki_pct": 60, "strike_pct": 70, "ac_pct": 100},
            {"ticker": "GOOGL", "name": "Alphabet (Google)",  "initial": 385.34, "ki_pct": 60, "strike_pct": 70, "ac_pct": 100},
            {"ticker": "NVDA",  "name": "NVIDIA Corporation", "initial": 225.00, "ki_pct": 60, "strike_pct": 70, "ac_pct": 100},
        ],
        "coupons_received": [
            {"date": "2026-07-01", "amount_usd": 1083.33, "note": "Period 1 — confirmed BOS transaction report 3 Jul 2026"},
        ],
    },

    # ── 3. European Banks Worst-of FCN — HSBA / GLE / UBS  (Goldman Sachs, XS3292699736) ──
    # Underlyings priced in local currencies (GBP / EUR) and USD (UBS NYSE).
    # UBS ticker: NYSE "UBS" in USD — confirmed from GS term sheet (Bloomberg: UBS UN Equity).
    {
        "id": "hsba_gle_ubs",
        "name": "European Banks Worst-of FCN",
        "issuer": "Goldman Sachs (ISIN: XS3292699736)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 1.1142,
        "coupon_annual_pct": 13.37,
        "issue_date": "2026-05-20",
        "maturity_date": "2027-06-07",
        "first_autocall_date": "2026-09-03",
        "autocall_freq": "Monthly",
        "ki_type": "European — KI checked only at Final Valuation Date (3 Jun 2027)",
        "underlyings": [
            {"ticker": "HSBA.L", "name": "HSBC Group",            "initial": 1329.0, "ki_pct": 65, "strike_pct": 75, "ac_pct": 100, "currency": "GBP"},
            {"ticker": "GLE.PA", "name": "Société Générale",      "initial": 67.05,  "ki_pct": 65, "strike_pct": 75, "ac_pct": 100, "currency": "EUR"},
            {"ticker": "UBS",    "name": "UBS AG (USD/NYSE)",     "initial": 46.22,  "ki_pct": 65, "strike_pct": 75, "ac_pct": 100, "currency": "USD"},
        ],
        "coupons_received": [
            {"date": "2026-07-08", "amount_usd": 1114.17, "note": "Period 1 — confirmed BOS transaction report 10 Jul 2026"},
        ],
    },

    # ── 4. Semiconductor Worst-of FCN — INTC / TSM / ASML  (Nomura, XS3361984373) ──
    {
        "id": "intc_tsm_asml",
        "name": "Semiconductor Worst-of FCN",
        "issuer": "Nomura (ISIN: XS3361984373)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 1.543,
        "coupon_annual_pct": 18.52,
        "issue_date": "2026-05-20",
        "maturity_date": "2027-06-07",
        "first_autocall_date": "2026-09-03",
        "autocall_freq": "Monthly (from 3rd observation, Sep 2026)",
        "ki_type": "European — KI checked only at Final Valuation Date (3 Jun 2027)",
        "underlyings": [
            {"ticker": "INTC", "name": "Intel Corporation",          "initial": 116.39,  "ki_pct": 50, "strike_pct": 60, "ac_pct": 95},
            {"ticker": "TSM",  "name": "Taiwan Semiconductor (ADR)", "initial": 397.60,  "ki_pct": 50, "strike_pct": 60, "ac_pct": 95},
            {"ticker": "ASML", "name": "ASML Holding",               "initial": 1500.63, "ki_pct": 50, "strike_pct": 60, "ac_pct": 95},
        ],
        "coupons_received": [
            {"date": "2026-07-08", "amount_usd": 1543.30, "note": "Period 1 — confirmed BOS transaction report 10 Jul 2026"},
        ],
    },

    # ── 5. Industrials Worst-of FCN — HON / SU / SIE  (HSBC, XS3376556539) ──
    # SIE initial 279.10 EUR confirmed from HSBC term sheet (Jun 2026).
    {
        "id": "hon_su_sie",
        "name": "Industrials Worst-of FCN",
        "issuer": "HSBC (ISIN: XS3376556539)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 1.0142,
        "coupon_annual_pct": 12.17,
        "issue_date": "2026-06-02",
        "maturity_date": "2027-06-21",
        "first_autocall_date": "2026-09-16",
        "autocall_freq": "Monthly",
        "ki_type": "European — KI checked only at Final Valuation Date (16 Jun 2027)",
        "underlyings": [
            {"ticker": "HON",   "name": "Honeywell International",  "initial": 235.94, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
            {"ticker": "SU.PA", "name": "Schneider Electric (EUR)", "initial": 282.10, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "EUR"},
            {"ticker": "SIE.DE","name": "Siemens AG (EUR)",          "initial": 279.10, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "EUR"},
        ],
        "coupons_received": [
            {"date": "2026-07-20", "amount_usd": 1014.17, "note": "Period 1 (DIARSC2619697304 — BOS tran report 22 Jul 2026)"},
        ],
    },

    # ── 6. US Banks Worst-of FCN — GS / JPM / MS  (SCB, XS3341866369) ──
    # Confirmed from BOS statement: GS.N, JPM.N, MS.N (Morgan Stanley — not Siemens)
    {
        "id": "gs_jpm_ms",
        "name": "Banks Worst-of FCN (Largest)",
        "issuer": "Standard Chartered (ISIN: XS3341866369)",
        "notional_usd": 200_000,
        "coupon_monthly_pct": 0.8958,
        "coupon_annual_pct": 10.75,
        "issue_date": "2026-06-02",
        "maturity_date": "2027-06-18",
        "first_autocall_date": "2026-09-16",
        "autocall_freq": "Monthly",
        "ki_type": "European — KI checked only at Final Valuation Date (16 Jun 2027)",
        "underlyings": [
            {"ticker": "GS",  "name": "Goldman Sachs",  "initial": 1049.74, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
            {"ticker": "JPM", "name": "JPMorgan Chase", "initial": 296.50,  "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
            {"ticker": "MS",  "name": "Morgan Stanley", "initial": 210.86,  "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
        ],
        "coupons_received": [
            {"date": "2026-07-20", "amount_usd": 1791.60, "note": "Period 1 (DIARSC2619685568 — BOS tran report 22 Jul 2026)"},
        ],
    },

    # ── 7. Asia ETF Worst-of FCN — EWY / EWJ / CQQQ  (Morgan Stanley, XS3373201808) ──
    {
        "id": "ms_asia_etf",
        "name": "Asia ETF Worst-of FCN",
        "issuer": "Morgan Stanley (ISIN: XS3373201808, Aa3/A+/AA)",
        "notional_usd": 150_000,
        "coupon_monthly_pct": 1.2925,
        "coupon_annual_pct": 15.51,
        "issue_date": "2026-06-17",
        "maturity_date": "2027-06-21",
        "first_autocall_date": "2026-09-17",
        "autocall_freq": "Monthly (17th)",
        "ki_type": "European — checked ONLY at maturity (17 Jun 2027)",
        "underlyings": [
            {"ticker": "EWY",  "name": "iShares MSCI South Korea ETF", "initial": 214.14, "ki_pct": 55, "strike_pct": 65, "ac_pct": 95},
            {"ticker": "EWJ",  "name": "iShares MSCI Japan ETF",        "initial": 94.25,  "ki_pct": 55, "strike_pct": 65, "ac_pct": 95},
            {"ticker": "CQQQ", "name": "Invesco China Technology ETF",   "initial": 53.82,  "ki_pct": 55, "strike_pct": 65, "ac_pct": 95},
        ],
        "coupons_received": [
            {"date": "2026-07-21", "amount_usd": 1938.75, "note": "Period 1 (DIARSC2619772044 — BOS tran report 22 Jul 2026)"},
        ],
    },

    # ── 8. Aerospace Worst-of FCN — AIR.PA / GE / SAF.PA  (HSBC, XS3377025971) ──
    {
        "id": "air_ge_saf",
        "name": "Aerospace Worst-of FCN",
        "issuer": "HSBC (ISIN: XS3377025971)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 1.02167,   # 12.26% / 12
        "coupon_annual_pct": 12.26,
        "issue_date": "2026-07-09",
        "maturity_date": "2027-07-13",
        "first_autocall_date": "2026-10-09",
        "autocall_freq": "Monthly (from 9 Oct 2026)",
        "ki_type": "European — KI at 65% of initial; checked ONLY at Final Valuation Date (9 Jul 2027)",
        "underlyings": [
            {"ticker": "AIR.PA", "name": "Airbus SE",        "initial": 193.28, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "EUR"},
            {"ticker": "GE",     "name": "General Electric", "initial": 356.84, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
            {"ticker": "SAF.PA", "name": "Safran SA",        "initial": 336.20, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "EUR"},
        ],
        "coupons_received": [],
    },

    # ── 9. TMO/JNJ/LLY Worst-of FCN  (OCBC, XS3425415935) ──
    # Term sheet dated 08-Jul-2026; settlement 22-Jul-2026; maturity 26-Jul-2027
    # Periods 1–2 are coupon-only; first autocall observation Period 3 (22 Oct 2026)
    # KI: 65% of initial, European (checked ONLY at Final Valuation Date 22 Jul 2027)
    {
        "id": "tmo_jnj_lly",
        "name": "TMO/JNJ/LLY Worst-of FCN",
        "issuer": "OCBC (ISIN: XS3425415935, Aa1/Moody's, AA-/S&P, AA-/Fitch)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 0.9767,   # 0.9767% × $100k = $976.70/month
        "coupon_annual_pct": 11.7204,   # 0.9767% × 12
        "issue_date": "2026-07-22",
        "maturity_date": "2027-07-26",  # Last Settlement Date (26 Jul 2027, 2 biz days after Final Valuation 22 Jul 2027)
        "first_autocall_date": "2026-10-22",  # Valuation Date 3 (Periods 1–2 are coupon-only)
        "autocall_freq": "Monthly from Period 3 (22-Oct-2026); Periods 1–2 are coupon-only",
        "ki_type": "European — KI at 65% of initial; checked ONLY at Final Valuation Date (22 Jul 2027); Strike at 75%",
        "underlyings": [
            {"ticker": "TMO",  "name": "Thermo Fisher Scientific Inc", "initial": 510.85,   "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
            {"ticker": "JNJ",  "name": "Johnson & Johnson",             "initial": 268.00,   "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
            {"ticker": "LLY",  "name": "Eli Lilly and Co",              "initial": 1_211.79, "ki_pct": 65, "strike_pct": 75, "ac_pct": 95, "currency": "USD"},
        ],
        "coupons_received": [],
    },

    # ── 10. AMZN/ORCL Worst-of FCN  (Nomura, XS3384042803) ──
    # Term sheet dated 02-Jul-2026; issue date 16-Jul-2026; maturity 20-Jul-2027
    # 15 securities × $10,000 = $150,000 notional
    # KO starts Period 3 (16-Oct-2026); Periods 1-2 are coupon-only (no KO obs)
    # KI: 50% of initial, European (checked ONLY at Final Valuation Date 16-Jul-2027)
    {
        "id": "amzn_orcl",
        "name": "AMZN/ORCL Worst-of FCN",
        "issuer": "Nomura International Funding Pte. Ltd. (ISIN: XS3384042803, Guarantor: Nomura Securities A-/S&P)",
        "notional_usd": 150_000,
        "coupon_monthly_pct": 1.1475,
        "coupon_annual_pct": 13.77,
        "issue_date": "2026-07-16",
        "maturity_date": "2027-07-20",
        "first_autocall_date": "2026-10-16",   # Period 3 — first KO observation date
        "autocall_freq": "Monthly from Period 3 (16-Oct-2026); Periods 1–2 are coupon-only",
        "ki_type": "European — KI at 50% of initial; checked ONLY at Final Valuation Date (16 Jul 2027); Strike at 60%",
        "underlyings": [
            {"ticker": "AMZN", "name": "Amazon.com Inc",    "initial": 241.70, "ki_pct": 50, "strike_pct": 60, "ac_pct": 95, "currency": "USD"},
            {"ticker": "ORCL", "name": "Oracle Corporation", "initial": 144.51, "ki_pct": 50, "strike_pct": 60, "ac_pct": 95, "currency": "USD"},
        ],
        "coupons_received": [],
    },

    # ── 11. DRAM Single-ETF FCN — Roundhill DRAM Memory ETF  (Morgan Stanley, XS3427736569) ──
    # Term sheet dated 22-Jul-2026 (MSI PLC). Single underlying ETF.
    # Trade/Strike 20-Jul-2026; issue 03-Aug-2026; Final Valuation 03-Feb-2027; maturity 05-Feb-2027.
    # Coupon 1.8392% per period × 6 periods = 11.04% over the 6M life (22.07% annualised).
    # First autocall observation 03-Nov-2026 (Period 3); Periods 1–2 coupon-only.
    {
        "id": "ms_dram",
        "name": "Roundhill DRAM Memory ETF FCN",
        "issuer": "Morgan Stanley (ISIN: XS3427736569, MSI PLC — Aa3/A+/AA)",
        "notional_usd": 100_000,
        "coupon_monthly_pct": 1.8392,   # 1.8392% per observation period (monthly)
        "coupon_annual_pct": 22.07,     # 1.8392% × 12
        "issue_date": "2026-08-03",
        "maturity_date": "2027-02-05",  # Maturity Date (2 biz days after Final Valuation 3 Feb 2027)
        "first_autocall_date": "2026-11-03",  # Period 3 — first autocall observation; Periods 1–2 coupon-only
        "autocall_freq": "Monthly from Period 3 (3-Nov-2026); Periods 1–2 are coupon-only",
        "ki_type": "European — KI at 50% of initial; checked ONLY at Final Valuation Date (3 Feb 2027); Strike at 60%",
        "underlyings": [
            {"ticker": "DRAM", "name": "Roundhill DRAM Memory ETF", "initial": 54.29,
             "ki_pct": 50, "strike_pct": 60, "ac_pct": 100, "currency": "USD"},
        ],
        "coupons_received": [],
    },
]

# ─── Bond / AT1 Positions ─────────────────────────────────────────────────────
BOND_POSITIONS = [
    {
        "id": "ubs_at1",
        "name": "UBS AT1 Perpetual Bond",
        "description": "UBSG 7.125 Perp '32 FRN",
        "isin": "CH1522231294",
        "issuer": "UBS Group AG (Aa3 / A+ / AA)",
        "type": "AT1 / Additional Tier 1 (CoCo)",
        "notional": 250_000,
        "currency": "AUD",
        "coupon_annual_pct": 7.125,
        "purchase_price_pct": 99.75,
        "purchase_date": "2026-06-10",
        "first_call_date": "2032-01-01",  # approximate
        "risks": [
            "Coupon can be cancelled at any time without triggering default",
            "Bond can be written down to zero if UBS CET1 falls below regulatory trigger",
            "Perpetual instrument — no guaranteed redemption date",
            "Subordinated: near bottom of capital stack in liquidation",
        ],
        "coupons_received": [
            # {"date": "2026-09-10", "amount_aud": 4453.13, "note": "Q1 coupon"}
        ],
    },
]

# ─── Direct Holdings (ETFs, stocks, bond funds) ──────────────────────────────
# Bond funds use ISIN as ticker — yfinance won't find them, so they always
# fall back to MANUAL_PRICES. Update the NAV there after each BOS statement.
DIRECT_HOLDINGS = [
    {
        "id": "gld",
        "name": "SPDR Gold Shares ETF",
        "ticker": "GLD",
        "isin": "US78463V1070",
        "shares": 57,
        "purchase_price": 434.7778,
        "currency": "USD",
    },
    {
        "id": "oih",
        "name": "VanEck Oil Services ETF",
        "ticker": "OIH",
        "isin": "US92189H6071",
        "shares": 57,
        "purchase_price": 440.5664,
        "currency": "USD",
    },
    # ── Bond Funds (Man Group) ────────────────────────────────────────────────
    # No exchange listing — NAV updated manually from BOS statements.
    # manual_price_only=True excludes these from yfinance fetch; MANUAL_PRICES
    # is always re-merged into the cache after every live price refresh.
    {
        "id": "man_dyna_inc",
        "name": "Man Dynamic Income Fund (Bond Fund)",
        "ticker": "IE00039W6MB8",   # ISIN used as price-dict key
        "isin": "IE00039W6MB8",
        "shares": 1_480,            # 990 units (26 May) + 490 units (4 Jun) confirmed BOS statement
        "purchase_price": 102.00,   # blended avg: ($101,059.89 + $49,900.77) / 1,480
        "currency": "USD",
        "manual_price_only": True,
        "dividends_received": [
            {"date": "2026-06-10", "amount_usd": 524.70, "note": "Jun distribution (DIARSC2615690480 — BOS ad-hoc statement)"},
            {"date": "2026-07-09", "amount_usd": 888.00, "note": "Jul distribution (DIARSC2618741318 — BOS ad-hoc statement)"},
        ],
    },
    {
        "id": "man_em_mkt_cor",
        "name": "Man Global InvGrade Opportunities Fund (Bond Fund)",
        "ticker": "IE000KEXCUV1",   # ISIN used as price-dict key
        "isin": "IE000KEXCUV1",
        "shares": 880,
        "purchase_price": 113.0190,
        "currency": "USD",
        "manual_price_only": True,
        "dividends_received": [
            {"date": "2026-06-10", "amount_usd": 457.60, "note": "Jun distribution (DIARSC2615518074 — BOS ad-hoc statement)"},
            {"date": "2026-07-09", "amount_usd": 528.00, "note": "Jul distribution (DIARSC2618794052 — BOS ad-hoc statement)"},
        ],
    },
    {
        "id": "shld",
        "name": "Global X Defense Tech ETF",
        "ticker": "SHLD",
        "isin": "US37960A5294",
        "shares": 390,
        "purchase_price": 62.0746,  # $24,209.09 total settled / 390 sh (incl. $239.69 commission; matches BOS unit cost)
        "currency": "USD",
        "dividends_received": [
            {"date": "2026-07-07", "amount_usd": 50.95, "note": "Dividend (DIARSC2618009010 — BOS 10 Jul report)"},
        ],
    },
    {
        "id": "msft",
        "name": "Microsoft Corporation",
        "ticker": "MSFT",
        "isin": "US5949181045",
        "shares": 65,
        "purchase_price": 380.0125,  # net $24,700.81 / 65 shares (incl. $244.56 commission); trade 29 Jun 2026
        "currency": "USD",
    },
    # ── Accumulator Deliveries (equity received from KO'd accumulators) ──────
    {
        "id": "googl_shares",
        "name": "Alphabet Inc Class A (accumulator deliveries)",
        "ticker": "GOOGL",
        "isin": "US02079K3059",
        "shares": 56,
        "purchase_price": 293.9751,  # blended: 38 sh @ $298.1035 (Accu #1) + 18 sh @ $285.2599 (Accu #2) = $16,462.61 / 56
        "currency": "USD",
        "note": "38 sh from GOOGL Accu #1 (KO 20 Jun) + 18 sh from Accu #2 (KO 29 Jun); confirmed BOS 30 Jun statement",
    },
    {
        "id": "lly_shares",
        "name": "Eli Lilly and Company (accumulator delivery)",
        "ticker": "LLY",
        "isin": "US5324571083",
        "shares": 39,
        "purchase_price": 919.7458,  # full guaranteed period (24 Jun–17 Aug) delivered in one batch on KO date; $35,870.09 total
        "currency": "USD",
        "note": "Guaranteed period delivery from LLY Accu (KO 24 Jun 2026); confirmed BOS 30 Jun statement",
    },
    {
        "id": "meta_shares",
        "name": "Meta Platforms Class A (accumulator delivery)",
        "ticker": "META",
        "isin": "US30303M1027",
        "shares": 38,
        "purchase_price": 464.0166,  # strike price = cost basis; total $17,632.63 (SCTRSC2618361926)
        "currency": "USD",
        "note": "38 sh from META Accu (KO 1 Jul 2026, close $612.91 vs barrier $590.0458); guaranteed period 18 Jun–13 Aug 2026",
    },
    # NOTE: QQQ and SPY shares (delivered in periodic batches from active accumulators) are NOT
    # listed here — they are already tracked in ACCUMULATOR_POSITIONS via _shares_accumulated().
    # Adding them here would double-count both the cost basis and portfolio value.
    # They will be added here only if/when those accumulators are KO'd and settled.
    {
        "id": "polar_cap_tech",
        "name": "Polar Capital Global Technology Fund (Dist - Cash)",
        "ticker": "IE00B433M743",   # ISIN used as price-dict key
        "isin": "IE00B433M743",
        "shares": 172.066,          # units purchased 30 Jun 2026 (value date 2 Jul 2026)
        "purchase_price": 290.5861, # $50,000 total settled / 172.066 units (incl. $248.76 commission; matches BOS unit cost)
        "currency": "USD",
        "manual_price_only": True,  # OTC fund — no yfinance listing; update NAV from BOS statements
    },
]

# ─── Accumulator Positions ────────────────────────────────────────────────────
ACCUMULATOR_POSITIONS = [
    # QQQ Accumulator — purchased 8 Jun 2026 (SYACDC2616000100)
    {
        "id": "qqq_accumulator",
        "name": "QQQ Accumulator",
        "issuer": "BOS (SYACDC2616000100)",
        "underlying_ticker": "QQQ",
        "underlying_name": "Invesco QQQ Trust",
        "start_date": "2026-06-08",
        "end_date": "2028-06-05",
        "strike_price": 573.977,
        "knockout_price": 753.816,
        "guaranteed_end": "2026-08-03",     # 8 weeks guaranteed
        "shares_per_day": 1,
        "leverage_below_strike": 2,
    },
    # SPY Accumulator — HSBC, trade date 11 Jun 2026
    {
        "id": "spy_accumulator",
        "name": "SPY Accumulator",
        "issuer": "HSBC (RFQ: 178043082)",
        "underlying_ticker": "SPY",
        "underlying_name": "SPDR S&P 500 ETF Trust",
        "start_date": "2026-06-11",
        "end_date": "2028-05-11",           # confirmed from BOS statement (SYACDC2616300154)
        "strike_price": 621.8292,           # 85.32% of spot 728.82
        "knockout_price": 765.2610,         # 105.00% of spot 728.82
        "guaranteed_end": "2026-07-09",     # 4 weeks guaranteed
        "shares_per_day": 1,
        "leverage_below_strike": 2,
    },
    # GOOGL Accumulator — MS, trade date 11 Jun 2026
    # SETTLED: 38 shares delivered (lump sum on KO date); now in DIRECT_HOLDINGS as part of 56 GOOGL shares
    {
        "id": "googl_accumulator",
        "name": "GOOGL Accumulator",
        "issuer": "Morgan Stanley (RFQ: 178043904)",
        "underlying_ticker": "GOOGL",
        "underlying_name": "Alphabet Inc",
        "start_date": "2026-06-11",
        "end_date": "2028-05-11",           # confirmed from BOS statement (SYACDC2616300192)
        "strike_price": 298.1035,           # 83.65% of spot 356.37
        "knockout_price": 367.0611,         # 103.00% of spot 356.37
        "guaranteed_end": "2026-08-06",     # 8 weeks guaranteed
        "shares_per_day": 1,
        "leverage_below_strike": 2,
        "settled": True,                    # all 38 shares delivered; tracked in DIRECT_HOLDINGS
        "shares_delivered": 38,             # confirmed BOS 30 Jun 2026 statement
    },
    # META Accumulator — Bank of Singapore, trade date 18 Jun 2026 (SYACDC2617000116)
    # SETTLED: 38 shares delivered (lump sum on KO date 1 Jul); now in DIRECT_HOLDINGS as meta_shares
    # KO'd at $612.91 vs barrier $590.0458 on 1 Jul 2026
    {
        "id": "meta_accumulator",
        "name": "META Accumulator",
        "issuer": "Bank of Singapore (SYACDC2617000116)",
        "underlying_ticker": "META",
        "underlying_name": "Meta Platforms Ord Shs Class A",
        "start_date": "2026-06-22",         # effective date
        "end_date": "2028-05-18",           # last period end date (482 fixing dates)
        "strike_price": 464.0166,           # 81% of spot 572.86
        "knockout_price": 590.0458,         # 103% of spot 572.86
        "guaranteed_end": "2026-08-13",     # guaranteed period: 18 Jun – 13 Aug 2026
        "shares_per_day": 1,
        "leverage_below_strike": 2,
        "settled": True,                    # all 38 shares delivered; tracked in DIRECT_HOLDINGS
        "shares_delivered": 38,             # confirmed BOS transaction report 3 Jul 2026 (SCTRSC2618361926)
    },
    # GOOGL Accumulator #2 — Bank of Singapore, trade date 29 Jun 2026 (SYACDC2618100004)
    # KO'd on trade date itself — GOOGL closed $353.65 vs KO barrier $352.7647
    # SETTLED: 18 guaranteed shares delivered in lump sum on 29 Jun; now in DIRECT_HOLDINGS as part of 56 GOOGL shares
    {
        "id": "googl_accumulator_2",
        "name": "GOOGL Accumulator #2",
        "issuer": "Bank of Singapore (SYACDC2618100004)",
        "underlying_ticker": "GOOGL",
        "underlying_name": "Alphabet Inc Class A",
        "start_date": "2026-06-30",         # effective date
        "end_date": "2027-06-28",           # 250 fixing dates from derivative closure doc (KO'd day 1, moot)
        "strike_price": 285.2599,           # 83.29% of spot $342.49
        "knockout_price": 352.7647,         # 103% of spot $342.49
        "guaranteed_end": "2026-07-13",     # guaranteed period: 29 Jun – 13 Jul 2026
        "shares_per_day": 2,
        "leverage_below_strike": 2,
        "settled": True,                    # all 18 shares delivered in one lump sum; tracked in DIRECT_HOLDINGS
        "shares_delivered": 18,             # confirmed BOS 30 Jun 2026 statement ($5,134.68 debit)
    },
    # LLY Accumulator — Bank of Singapore, trade date 22 Jun 2026 (SYACDC2617400100)
    # SETTLED: 39 shares (full guaranteed period 24 Jun–17 Aug) delivered as lump sum on KO date; now in DIRECT_HOLDINGS
    {
        "id": "lly_accumulator",
        "name": "LLY Accumulator",
        "issuer": "Bank of Singapore (SYACDC2617400100)",
        "underlying_ticker": "LLY",
        "underlying_name": "Eli Lilly and Co",
        "start_date": "2026-06-23",         # effective date
        "end_date": "2028-05-22",           # period 50 end date (483 fixing dates)
        "strike_price": 919.746,            # 82.86% of spot $1,110
        "knockout_price": 1143.30,          # 103% of spot $1,110
        "guaranteed_end": "2026-08-17",     # guaranteed period: 22 Jun – 17 Aug 2026
        "shares_per_day": 1,
        "leverage_below_strike": 2,
        "settled": True,                    # all 39 shares delivered in one lump sum; tracked in DIRECT_HOLDINGS
        "shares_delivered": 39,             # confirmed BOS 30 Jun 2026 statement ($35,870.09 total)
    },
]

# ═════════════════════════════════════════════════════════════════════════════
#  MANUAL PRICE FALLBACK  (updated 15 Jul 2026 from BOS ad-hoc statement)
#  These are used automatically if yfinance cannot connect.
# ═════════════════════════════════════════════════════════════════════════════

MANUAL_PRICES = {
    # USD ETFs (15 Jul 2026 prices from BOS ad-hoc statement)
    "SPY":   754.81,
    "QQQ":   717.74,
    "LLY":   1156.63,
    "DIA":   500.25,    # no update in this statement
    # US Tech
    "META":  681.31,    # 15 Jul 2026
    "GOOGL": 370.92,    # 15 Jul 2026
    "NVDA":  200.42,    # no update in this statement
    "MSFT":  395.63,    # 15 Jul 2026
    # Semiconductors
    "INTC":  107.04,    # no update in this statement
    "TSM":   408.75,    # no update in this statement
    "ASML":  1734.19,   # no update in this statement
    # Industrials (USD)
    "HON":   205.88,    # no update in this statement
    # US Banks
    "GS":    1001.29,   # no update in this statement
    "JPM":   309.14,    # no update in this statement
    "MS":    206.66,    # no update in this statement
    # Asia ETFs
    "EWY":   179.00,    # no update in this statement
    "EWJ":   90.98,     # no update in this statement
    "CQQQ":  54.00,     # no update in this statement
    # Direct ETF holdings (15 Jul 2026 from BOS statement)
    "GLD":   372.35,
    "OIH":   382.06,
    "SHLD":  60.26,     # Global X Defense Tech ETF (BOS 15 Jul 2026)
    # Bond funds (Man Group) — updated from BOS ad-hoc statement 15 Jul 2026
    "IE00039W6MB8": 100.85,   # Man Dynamic Income — NAV USD (BOS 15 Jul 2026)
    "IE000KEXCUV1": 112.29,   # Man Global InvGrade Opps — NAV USD (BOS 15 Jul 2026)
    # European (local currency)
    "HSBA.L":  1329.20,   # GBp — no update in this statement
    "GLE.PA":  69.87,     # EUR — no update in this statement
    "UBS":     46.77,     # USD (NYSE) — no update in this statement
    "SU.PA":   261.50,    # EUR — no update in this statement
    "SIE.DE":  279.10,    # EUR — no update in this statement
    # Aerospace FCN underlyings (HSBC XS3377025971)
    "AIR.PA":  193.28,    # EUR — Airbus SE initial price (no update)
    "GE":      356.84,    # USD — General Electric initial price (no update)
    "SAF.PA":  336.20,    # EUR — Safran SA initial price (no update)
    # OTC fund — updated from BOS ad-hoc statement 15 Jul 2026
    "IE00B433M743": 263.34,  # Polar Capital Global Technology Fund — NAV USD (BOS 15 Jul 2026)
    # Roundhill DRAM Memory ETF (MS FCN XS3427736569) — yfinance ticker "DRAM"; fallback = initial price
    "DRAM": 54.29,   # Bats Z-exchange; initial price 20 Jul 2026 (fallback if live fetch fails)
}
MANUAL_PRICES_DATE = "2026-07-15"

# ═════════════════════════════════════════════════════════════════════════════
#  PRICE FETCHING
# ═════════════════════════════════════════════════════════════════════════════

def _fetch_man_fund_navs() -> dict:
    """Fetch live NAVs for OTC funds (Man Group + Polar Capital) via FT.com."""
    import urllib.request, re
    navs = {}

    # All manual_price_only holdings keyed by ISIN → display name
    FUNDS = {
        "IE00039W6MB8": "Man Dynamic Income",
        "IE000KEXCUV1": "Man Global InvGrade",
        "IE00B433M743": "Polar Capital Global Tech",
    }

    hdrs = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://markets.ft.com/",
    }

    for isin, name in FUNDS.items():
        try:
            url = f"https://markets.ft.com/data/funds/tearsheet/summary?s={isin}"
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode(errors="replace")
            m = re.search(r'"price"\s*:\s*\{\s*"value"\s*:\s*"?([\d.]+)"?', html)
            if not m:
                m = re.search(r'class="mod-ui-data-list__value"[^>]*>([\d.]+)<', html)
            if not m:
                m = re.search(r'"lastPrice"\s*:\s*([\d.]+)', html)
            if m:
                price = float(m.group(1))
                if price > 0:
                    navs[isin] = round(price, 4)
                    print(f"  📊 {name}: ${navs[isin]} (FT.com)")
            else:
                print(f"  ⚠ Fund {name}: price not found on FT.com")
        except Exception as e:
            print(f"  ⚠ Fund {name} FT.com: {e}")

    return navs

def fetch_prices(tickers: list) -> tuple:
    """Returns (prices, prev_closes) dicts.
    prev_closes maps ticker → previous session's closing price (for intraday % change)."""
    prices      = {}
    prev_closes = {}
    if not tickers:
        return prices, prev_closes
    print(f"📡 Fetching live prices: {', '.join(tickers)}")
    for t in tickers:
        try:
            obj  = yf.Ticker(t)
            fi   = obj.fast_info
            p    = fi.last_price
            if p and float(p) > 0:
                prices[t] = round(float(p), 4)
            else:
                hist = obj.history(period="2d")
                if not hist.empty:
                    prices[t] = round(float(hist["Close"].iloc[-1]), 4)
                else:
                    print(f"  ⚠ {t}: no price data")
            # Collect previous close for intraday % change on holding cards
            pc = getattr(fi, "previous_close", None)
            if pc and float(pc) > 0:
                prev_closes[t] = round(float(pc), 4)
        except Exception as e:
            print(f"  ⚠ {t}: {e}")
    return prices, prev_closes

def _nyse_is_closed():
    """Return True if NYSE is currently closed (before 9:30am ET, after 4:00pm ET, or weekend).
    Uses zoneinfo (Python 3.9+) with UTC-4 fallback."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except Exception:
        et = _dt.timezone(_dt.timedelta(hours=-4))   # EDT approximation
    now = _dt.datetime.now(et)
    if now.weekday() >= 5:   # Saturday / Sunday
        return True
    open_  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_ = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return now < open_ or now >= close_

def fetch_close_prices(tickers: list):
    """Fetch last CONFIRMED daily closing prices for KO checks.
    - During market hours (9:30–16:00 ET): exclude today's bar — it's incomplete/intraday.
    - After market close / weekend: include today's bar — it's the official confirmed close.
    Returns (prices_dict, dates_dict) — dates_dict maps ticker → YYYY-MM-DD of that close."""
    closes        = {}
    dates         = {}
    today         = date.today()
    mkt_closed    = _nyse_is_closed()
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="5d", interval="1d")
            if not hist.empty:
                if mkt_closed:
                    # Market closed — today's bar (if present) IS the confirmed official close
                    row = hist
                else:
                    # Market open — drop today's incomplete intraday bar
                    prior = hist[hist.index.date < today]
                    row   = prior if not prior.empty else hist
                closes[t] = round(float(row["Close"].iloc[-1]), 4)
                dates[t]  = row.index[-1].date().isoformat()
                print(f"  📅 {t} close: ${closes[t]} ({dates[t]}) [mkt {'closed' if mkt_closed else 'open'}]")
        except Exception as e:
            print(f"  ⚠ close price {t}: {e}")
    return closes, dates

# ── Double-up day logging ──────────────────────────────────────────────────────
# Persists to accumulator_double_up_log.json in the same directory as the script.
# Records every date a confirmed closing price was BELOW strike for each accumulator.
# These extra shares are permanent — even if price recovers, the 2× obligation remains.

import json as _json

_DU_LOG_FILE = Path(__file__).parent / "accumulator_double_up_log.json"
_KO_LOG_FILE = Path(__file__).parent / "accumulator_ko_log.json"

def _load_du_log():
    try:
        if _DU_LOG_FILE.exists():
            return _json.loads(_DU_LOG_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_du_log(log):
    try:
        _DU_LOG_FILE.write_text(_json.dumps(log, indent=2))
    except Exception as e:
        print(f"  ⚠ Could not save double-up log: {e}")

def _load_ko_log():
    """Load KO log: hardcoded KNOWN_KO_EVENTS (works everywhere) merged with
    the local file log (auto-updated on Mac/local, not available on Render)."""
    log = dict(KNOWN_KO_EVENTS)   # start from hardcoded config
    try:
        if _KO_LOG_FILE.exists():
            file_log = _json.loads(_KO_LOG_FILE.read_text())
            log.update(file_log)  # file entries override/extend hardcoded ones
    except Exception:
        pass
    return log

def _save_ko_log(log):
    try:
        _KO_LOG_FILE.write_text(_json.dumps(log, indent=2))
    except Exception as e:
        print(f"  ⚠ Could not save KO log: {e}")

def _update_ko_log(closes, close_dates):
    """Permanently record KO events. Once closing price >= KO barrier, always KO — even if
    price later recovers. Returns the current KO log dict."""
    log     = _load_ko_log()
    changed = False
    for acc in ACCUMULATOR_POSITIONS:
        aid   = acc["id"]
        if aid in log:
            continue  # already permanently knocked out
        t     = acc.get("underlying_ticker", "")
        ko    = acc.get("knockout_price")
        close = closes.get(t)
        cdate = close_dates.get(t, date.today().isoformat())
        if not (ko and close and cdate):
            continue
        if float(close) >= float(ko):
            log[aid] = {
                "ko_date":          cdate,
                "ko_price":         round(float(close), 4),
                "ticker":           t,
                "knockout_barrier": ko,
            }
            print(f"  🔴 KO CONFIRMED: {acc.get('name')} @ ${close:.2f} on {cdate} (barrier ${ko:.4f})")
            changed = True
    if changed:
        _save_ko_log(log)
    return log

def _update_du_log(closes, close_dates):
    """Log any new dates where a confirmed close was below strike (2× leverage day).
    Does not log once the accumulator is permanently KO'd."""
    ko_log  = _load_ko_log()
    log     = _load_du_log()
    changed = False
    for acc in ACCUMULATOR_POSITIONS:
        aid    = acc["id"]
        if aid in ko_log:
            continue  # KO'd — accumulation stopped, no more 2× days
        t      = acc.get("underlying_ticker", "")
        strike = acc.get("strike_price")
        close  = closes.get(t)
        cdate  = close_dates.get(t)
        if not (strike and close and cdate):
            continue
        # Only log within the accumulator's active period
        start = acc.get("start_date", "")
        end   = acc.get("end_date", "9999-12-31")
        if not (start <= cdate <= end):
            continue
        if aid not in log:
            log[aid] = {"double_up_dates": []}
        if close < strike and cdate not in log[aid]["double_up_dates"]:
            log[aid]["double_up_dates"].append(cdate)
            print(f"  📝 Logged 2× day for {aid}: {cdate} (close {close:.2f} < strike {strike:.2f})")
            changed = True
    if changed:
        _save_du_log(log)

# ═════════════════════════════════════════════════════════════════════════════
#  STATUS COMPUTATION
# ═════════════════════════════════════════════════════════════════════════════

def underlying_status(u: dict, prices: dict) -> dict:
    ticker     = u["ticker"]
    init       = u.get("initial")
    ki_pct     = u.get("ki_pct")
    strike_pct = u.get("strike_pct")
    ac_pct     = u.get("ac_pct")
    current    = prices.get(ticker)

    ki_lvl  = round(init * ki_pct     / 100, 4) if (init and ki_pct)     else None
    str_lvl = round(init * strike_pct / 100, 4) if (init and strike_pct) else None
    ac_lvl  = round(init * ac_pct     / 100, 4) if (init and ac_pct)     else None
    curr_pct_of_init = round(current / init * 100, 2) if (current and init) else None

    status = "UNKNOWN"
    if curr_pct_of_init is not None and ki_pct is not None:
        if curr_pct_of_init < ki_pct:
            status = "BREACH"
        elif curr_pct_of_init < ki_pct * 1.20:
            status = "WATCH"
        else:
            status = "SAFE"

    pct_above_ki = round((current / ki_lvl  - 1) * 100, 2) if (current and ki_lvl)  else None
    pct_above_ac = round((current / ac_lvl  - 1) * 100, 2) if (current and ac_lvl)  else None

    return {
        "ticker": ticker, "name": u["name"],
        "initial": init, "current": current,
        "ki_lvl": ki_lvl, "str_lvl": str_lvl, "ac_lvl": ac_lvl,
        "ki_pct": ki_pct, "strike_pct": strike_pct, "ac_pct": ac_pct,
        "curr_pct": curr_pct_of_init,
        "pct_above_ki": pct_above_ki,
        "pct_above_ac": pct_above_ac,
        "status": status,
        "currency": u.get("currency", "USD"),
        "missing_data": (init is None or ki_pct is None),
    }

def accumulator_status(acc: dict, prices: dict, closes=None) -> dict:
    t       = acc.get("underlying_ticker", "")
    current = prices.get(t)
    close   = (closes or {}).get(t)   # last confirmed daily close
    strike  = acc.get("strike_price")
    ko      = acc.get("knockout_price")
    g_end   = acc.get("guaranteed_end")
    today   = date.today().isoformat()

    # Settled: shares fully delivered and moved to DIRECT_HOLDINGS — no longer an open position
    if acc.get("settled"):
        ko_log    = _load_ko_log()
        ko_record = ko_log.get(acc.get("id", ""))
        return {**acc, "current": current, "close": close, "status": "SETTLED",
                "knocked_out": True, "near_ko": False,
                "in_guaranteed": False, "below_strike": False,
                "ko_record": ko_record}

    # Permanent KO: once logged, always KO — even if price later recovers
    ko_log    = _load_ko_log()
    ko_record = ko_log.get(acc.get("id", ""))
    knocked_out   = bool(ko_record)
    # Also check current close in case today is the first KO day (log updated separately)
    if not knocked_out:
        knocked_out = bool(close and ko and close >= ko)
    near_ko       = bool(not knocked_out and current and ko and current >= ko)  # intraday warning
    in_guaranteed = bool(g_end and today <= g_end)
    below_strike  = bool(not knocked_out and current and strike and current < strike)

    if knocked_out:          status = "KNOCKED_OUT"
    elif near_ko:            status = "NEAR_KO"
    elif in_guaranteed:      status = "GUARANTEED"
    elif below_strike:       status = "DOUBLE_UP"
    elif current:            status = "ACCUMULATING"
    else:                    status = "UNKNOWN"

    return {**acc, "current": current, "close": close, "status": status,
            "knocked_out": knocked_out, "near_ko": near_ko,
            "in_guaranteed": in_guaranteed, "below_strike": below_strike,
            "ko_record": ko_record}

# ═════════════════════════════════════════════════════════════════════════════
#  HTML DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     background:#f1f5f9;color:#1e293b;font-size:14px}
.hdr{background:linear-gradient(135deg,#1e3a5f,#2563eb);color:#fff;
     padding:20px 32px;display:flex;justify-content:space-between;align-items:center}
.hdr h1{font-size:18px;font-weight:700}
.hdr .sub{opacity:.7;font-size:12px;margin-top:3px}
.hdr .ts{text-align:right;font-size:12px;opacity:.8;line-height:1.6}
.wrap{max-width:1080px;margin:24px auto;padding:0 16px}
.sec{font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;
     letter-spacing:.1em;margin:28px 0 10px}
.card{background:#fff;border-radius:12px;padding:20px 24px;margin-bottom:14px;
      box-shadow:0 1px 3px rgba(0,0,0,.07)}
.ch{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}
.ct{font-size:15px;font-weight:700}
.cm{font-size:12px;color:#64748b;margin-top:3px;line-height:1.7}
.badge{display:inline-block;padding:2px 9px;border-radius:20px;color:#fff;
       font-size:11px;font-weight:700;letter-spacing:.03em}
.ab{border-radius:9px;padding:11px 15px;margin-bottom:12px;font-weight:600;font-size:13px}
.ab-e{background:#fef2f2;border:1px solid #fecaca;color:#dc2626}
.ab-w{background:#fffbeb;border:1px solid #fde68a;color:#b45309}
.ab-g{background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d}
.urow{border:1px solid #f1f5f9;border-radius:8px;padding:12px 16px;margin-bottom:8px}
.urow.worst{border-color:#bfdbfe;background:#eff6ff}
.utop{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:8px}
.tick{font-weight:700;font-size:15px;color:#1e3a8a}
.uname{color:#64748b;font-size:12px;margin-left:6px}
.cprice{font-size:18px;font-weight:700;text-align:right}
.cpct{font-size:12px;color:#64748b}
.wtag{font-size:10px;background:#1e3a8a;color:#fff;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}
/* Gauge */
.gw{position:relative;height:36px;margin:6px 0 22px}
.gt{position:absolute;top:10px;left:0;right:0;height:12px;border-radius:6px;
    background:#e2e8f0;overflow:visible}
.zn{position:absolute;top:0;height:100%}
.zn-r{background:#fca5a5;border-radius:6px 0 0 6px}
.zn-o{background:#fed7aa}
.zn-y{background:#fef08a}
.zn-g{background:#86efac;border-radius:0 6px 6px 0}
.mk{position:absolute;top:-5px;width:2px;height:22px}
.mk-ki{background:#dc2626}
.mk-st{background:#f59e0b}
.mk-ac{background:#22c55e}
.mlb{position:absolute;top:19px;font-size:9px;font-weight:700;color:#475569;
     transform:translateX(-50%);white-space:nowrap}
.dot{position:absolute;top:2px;width:10px;height:10px;border-radius:50%;
     border:2px solid #fff;transform:translateX(-50%);z-index:10;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.glvl{display:flex;gap:14px;flex-wrap:wrap;margin-top:2px}
.li{display:flex;align-items:center;gap:4px;font-size:11px;color:#475569}
.ld{width:8px;height:8px;border-radius:2px;flex-shrink:0}
.buf{margin-left:auto;font-weight:600;font-size:12px;color:#334155}
/* Income */
.is{margin-top:14px;border-top:1px solid #f1f5f9;padding-top:14px}
.ig{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}
.il{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
.iv{font-size:16px;font-weight:700;margin-top:2px}
.ct2{width:100%;border-collapse:collapse;font-size:12px}
.ct2 th{text-align:left;color:#94a3b8;font-weight:600;padding:4px 8px;border-bottom:1px solid #f1f5f9}
.ct2 td{padding:5px 8px;border-bottom:1px solid #f8fafc}
.ec{color:#94a3b8;font-size:12px;font-style:italic;padding:6px 0}
.cpay-grid{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.cpay{border-radius:8px;padding:6px 10px;min-width:62px;text-align:center;font-size:11px;cursor:default}
.cpay-m{font-weight:700;margin-bottom:2px;font-size:11px}
.cpay-a{font-size:10px;opacity:0.9}
.cpaid{background:#dcfce7;color:#15803d;border:1px solid #86efac}
.cpend{background:#f8fafc;color:#94a3b8;border:1px solid #e2e8f0}
.cnext{background:#fef9c3;color:#854d0e;border:1px solid #fde68a}
.cmiss{background:#fee2e2;color:#b91c1c;border:1px solid #fca5a5}
.miss{background:#fafafa;border:1px dashed #cbd5e1;border-radius:7px;padding:11px 14px;
      color:#94a3b8;font-size:12px}
.miss strong{color:#f59e0b}
/* Summary */
.sg{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:4px}
.sc{background:#fff;border-radius:10px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.sl{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}
.sv{font-size:22px;font-weight:700;margin-top:3px}
.ss{font-size:11px;color:#64748b;margin-top:2px}
.rk{list-style:none;padding:0}
.rk li{font-size:12px;color:#64748b;padding:3px 0}
.rk li::before{content:"⚠ ";color:#f59e0b}
footer{text-align:center;padding:24px;color:#94a3b8;font-size:11px}
"""

def gauge(curr_pct, ki_pct, strike_pct, ac_pct):
    if curr_pct is None:
        return '<div style="color:#94a3b8;font-size:12px;padding:4px 0">Live price unavailable</div>'
    MAX = 130.0
    def p(v): return f"{min(v/MAX*100,99.8):.1f}%"
    ki  = ki_pct or 0
    st  = strike_pct or ki
    ac  = ac_pct or 100
    zones = (f'<div class="zn zn-r" style="width:{p(ki)}"></div>'
             f'<div class="zn zn-o" style="left:{p(ki)};width:{p(max(st-ki,0))}"></div>'
             f'<div class="zn zn-y" style="left:{p(st)};width:{p(max(ac-st,0))}"></div>'
             f'<div class="zn zn-g" style="left:{p(ac)};width:{p(max(MAX-ac,0))}"></div>')
    marks = ""
    if ki_pct and strike_pct and ki_pct == strike_pct:
        marks += f'<div class="mk mk-ki" style="left:{p(ki_pct)}"><div class="mlb">KI=Str {ki_pct}%</div></div>'
    else:
        if ki_pct:     marks += f'<div class="mk mk-ki" style="left:{p(ki_pct)}"><div class="mlb">KI {ki_pct}%</div></div>'
        if strike_pct: marks += f'<div class="mk mk-st" style="left:{p(strike_pct)}"><div class="mlb">Str {strike_pct}%</div></div>'
    if ac_pct:     marks += f'<div class="mk mk-ac" style="left:{p(ac_pct)}"><div class="mlb">AC {ac_pct}%</div></div>'
    dot_clr = ("#ef4444" if (ki_pct and curr_pct < ki_pct) else
               "#f59e0b" if (ki_pct and curr_pct < ki_pct * 1.20) else "#3b82f6")
    marks += f'<div class="dot" style="left:{p(curr_pct)};background:{dot_clr}"></div>'
    return f'<div class="gw"><div class="gt">{zones}{marks}</div></div>'

STATUS_COLOR = {"SAFE":"#22c55e","WATCH":"#f59e0b","BREACH":"#ef4444","UNKNOWN":"#94a3b8"}
STATUS_LABEL = {"SAFE":"✓ SAFE","WATCH":"⚠ WATCH","BREACH":"✖ KI BREACHED","UNKNOWN":"Details needed"}

def _expected_coupon_dates(fcn):
    """
    Return list of expected coupon observation dates for a monthly-pay FCN.
    Formula: first coupon = first_autocall_date − 2 months (covers 3-month first-AC structure);
    then monthly until maturity.
    """
    import calendar as _cal
    first_ac_str = fcn.get("first_autocall_date", "")
    maturity_str = fcn.get("maturity_date", "")
    if not first_ac_str or not maturity_str:
        return []
    try:
        first_ac = date.fromisoformat(first_ac_str)
        maturity = date.fromisoformat(maturity_str)
        # Step back 2 months to get first coupon date
        m, y = first_ac.month - 2, first_ac.year
        if m <= 0:
            m += 12; y -= 1
        d   = min(first_ac.day, _cal.monthrange(y, m)[1])
        cur = date(y, m, d)
        dates = []
        while cur <= maturity:
            dates.append(cur)
            m, y = cur.month + 1, cur.year
            if m > 12:
                m = 1; y += 1
            d   = min(cur.day, _cal.monthrange(y, m)[1])
            cur = date(y, m, d)
        return dates
    except Exception:
        return []

def _match_coupons_to_schedule(received, expected_dates):
    """
    Match each received coupon to its nearest expected date (within 10 calendar days).
    Returns dict: expected_date → coupon record.
    """
    matched = {}
    pool    = list(received)
    for exp in expected_dates:
        best_i, best_delta = None, 999
        for i, c in enumerate(pool):
            try:
                rec_d = date.fromisoformat(str(c["date"]))
                delta = abs((rec_d - exp).days)
                if delta <= 10 and delta < best_delta:
                    best_i, best_delta = i, delta
            except Exception:
                pass
        if best_i is not None:
            matched[exp] = pool.pop(best_i)
    return matched

def fcn_card(fcn, prices):
    us = [underlying_status(u, prices) for u in fcn.get("underlyings", [])]
    with_curr = [u for u in us if u["curr_pct"] is not None]
    worst_tick = min(with_curr, key=lambda u: u["curr_pct"])["ticker"] if with_curr else None
    statuses   = [u["status"] for u in us]
    overall    = "BREACH" if "BREACH" in statuses else "WATCH" if "WATCH" in statuses else "SAFE" if "SAFE" in statuses else "UNKNOWN"

    notional   = fcn.get("notional_usd") or 0
    m_pct      = fcn.get("coupon_monthly_pct") or 0
    a_pct      = fcn.get("coupon_annual_pct") or (m_pct * 12)
    m_inc      = notional * m_pct / 100 if (notional and m_pct) else None
    a_inc      = notional * a_pct / 100 if (notional and a_pct) else None
    received   = fcn.get("coupons_received", [])
    total_rcvd = sum(c.get("amount_usd", 0) for c in received)

    # Underlying rows
    rows = ""
    for u in us:
        is_worst = (u["ticker"] == worst_tick)
        wtag = '<span class="wtag">WORST</span>' if is_worst else ""
        worst_cls = " worst" if is_worst else ""
        ccy     = u.get("currency", "USD")
        sym     = {"USD": "$", "GBP": "£", "EUR": "€", "CHF": "CHF "}.get(ccy, "$")
        if u["missing_data"]:
            body = ('<div class="miss"><strong>⚠ Term sheet details needed.</strong> '
                    'Add initial price, ki_pct, strike_pct, ac_pct to the config above.</div>')
        else:
            g = gauge(u["curr_pct"], u["ki_pct"], u["strike_pct"], u["ac_pct"])
            buf_txt = (f'+{u["pct_above_ki"]:.1f}% above KI' if (u["pct_above_ki"] and u["pct_above_ki"] > 0)
                       else f'<span style="color:#dc2626">{u["pct_above_ki"]:.1f}% — KI BREACHED</span>' if u["pct_above_ki"] is not None
                       else "—")
            ac_txt  = ('✓ Autocall range' if (u["pct_above_ac"] is not None and u["pct_above_ac"] >= 0)
                       else f'Needs +{abs(u["pct_above_ac"]):.1f}% for autocall' if u["pct_above_ac"] is not None else "—")
            lvls    = (f'<div class="li"><div class="ld" style="background:#fca5a5"></div> KI: {sym}{u["ki_lvl"]:,.2f} ({u["ki_pct"]}%)</div>'
                       f'<div class="li"><div class="ld" style="background:#fed7aa"></div> Strike: {sym}{u["str_lvl"]:,.2f} ({u["strike_pct"]}%)</div>'
                       f'<div class="li"><div class="ld" style="background:#86efac"></div> Autocall: {sym}{u["ac_lvl"]:,.2f} ({u["ac_pct"]}%)</div>'
                       f'<div class="buf">{buf_txt} &nbsp;|&nbsp; {ac_txt}</div>')
            body = f'{g}<div class="glvl">{lvls}</div>'
        pr_str  = f'{sym}{u["current"]:,.2f}' if u["current"] else "—"
        pct_str = f'{u["curr_pct"]:.1f}% of initial' if u["curr_pct"] else ""
        b_clr   = STATUS_COLOR.get(u["status"], "#94a3b8")
        b_lbl   = STATUS_LABEL.get(u["status"], u["status"])
        rows += (f'<div class="urow{worst_cls}">'
                 f'<div class="utop">'
                 f'<div><span class="tick">{u["ticker"]}</span><span class="uname">{u["name"]}</span>{wtag}</div>'
                 f'<div><div class="cprice">{pr_str}</div><div class="cpct">{pct_str}</div></div>'
                 f'<span class="badge" style="background:{b_clr}">{b_lbl}</span>'
                 f'</div>{body}</div>')

    # Coupon payment schedule
    today_d       = date.today()
    expected_dates = _expected_coupon_dates(fcn)
    matched        = _match_coupons_to_schedule(received, expected_dates)
    n_exp          = len(expected_dates)
    n_rcvd         = len(matched)

    if expected_dates:
        # Build chip grid — one chip per expected coupon period
        chips = ""
        for i, exp in enumerate(expected_dates):
            rec       = matched.get(exp)
            period_no = i + 1
            label     = exp.strftime("%b '%y")
            if rec:
                amt_str  = f"${rec.get('amount_usd', 0):,.0f}"
                note_tip = rec.get("note", f"Period {period_no}")
                chips += (f'<div class="cpay cpaid" title="{note_tip}">'
                          f'<div class="cpay-m">✓ {label}</div>'
                          f'<div class="cpay-a">{amt_str}</div>'
                          f'</div>')
            elif exp <= today_d:
                # Past — not yet in system (shouldn't normally occur)
                chips += (f'<div class="cpay cmiss" title="Period {period_no} — not yet logged">'
                          f'<div class="cpay-m">{label}</div>'
                          f'<div class="cpay-a">—</div>'
                          f'</div>')
            elif (exp - today_d).days <= 30:
                # Due within ~1 month — highlight
                exp_amt  = f"${m_inc:,.0f}" if m_inc else "~"
                due_str  = exp.strftime("%d %b %Y")
                chips += (f'<div class="cpay cnext" title="Period {period_no} — due {due_str}">'
                          f'<div class="cpay-m">{label}</div>'
                          f'<div class="cpay-a">{exp_amt}</div>'
                          f'</div>')
            else:
                exp_amt  = f"${m_inc:,.0f}" if m_inc else "~"
                due_str  = exp.strftime("%d %b %Y")
                chips += (f'<div class="cpay cpend" title="Period {period_no} — due {due_str}">'
                          f'<div class="cpay-m">{label}</div>'
                          f'<div class="cpay-a">{exp_amt}</div>'
                          f'</div>')

        total_expected = (m_inc or 0) * n_exp
        summary = (f'<div style="font-size:12px;color:#64748b;margin-bottom:6px">'
                   f'<span style="color:#15803d;font-weight:600">{n_rcvd} paid</span>'
                   f' · {n_exp - n_rcvd} pending'
                   f' · <span style="font-weight:600">${total_rcvd:,.2f} received</span>'
                   f' of ${total_expected:,.2f} total'
                   f'</div>')
        coupon_html = summary + f'<div class="cpay-grid">{chips}</div>'
    else:
        if received:
            trows = "".join(f"<tr><td>{c['date']}</td><td>${c.get('amount_usd',0):,.2f}</td><td>{c.get('note','')}</td></tr>" for c in received)
            trows += f'<tr style="font-weight:700"><td>Total</td><td>${total_rcvd:,.2f}</td><td></td></tr>'
            coupon_html = f'<table class="ct2"><tr><th>Date</th><th>Amount (USD)</th><th>Note</th></tr>{trows}</table>'
        else:
            coupon_html = '<div class="ec">No coupons logged yet.</div>'

    m_str   = f'${m_inc:,.2f}/month' if m_inc else "—"
    a_str   = f'${a_inc:,.2f}/year ({a_pct:.2f}% p.a.)' if a_inc else f'{a_pct:.2f}% p.a. (notional TBD)' if a_pct else "—"
    n_str   = f'${notional:,.0f}' if notional else "—"
    b_clr   = STATUS_COLOR.get(overall, "#94a3b8")
    b_lbl   = STATUS_LABEL.get(overall, overall)

    return (f'<div class="card">'
            f'<div class="ch"><div>'
            f'<div class="ct">{fcn["name"]} &nbsp;<span class="badge" style="background:{b_clr}">{b_lbl}</span></div>'
            f'<div class="cm">{fcn["issuer"]} · Notional: {n_str} · Coupon: {a_pct:.2f}% p.a. ({m_str})</div>'
            f'<div class="cm">Maturity: {fcn.get("maturity_date","—")} · First autocall: {fcn.get("first_autocall_date","—")} · {fcn.get("autocall_freq","—")}</div>'
            f'<div class="cm">KI type: {fcn.get("ki_type","—")}</div>'
            f'</div></div>'
            f'{rows}'
            f'<div class="is"><div style="font-weight:700;font-size:13px;margin-bottom:10px">Coupon Income</div>'
            f'<div class="ig">'
            f'<div><div class="il">Monthly income</div><div class="iv">{m_str}</div></div>'
            f'<div><div class="il">Annual income</div><div class="iv">{a_str}</div></div>'
            f'<div><div class="il">Total received</div><div class="iv">${total_rcvd:,.2f}</div></div>'
            f'</div>{coupon_html}</div></div>')

def bond_card(b):
    notional  = b["notional"]
    currency  = b["currency"]
    a_pct     = b["coupon_annual_pct"]
    a_inc     = notional * a_pct / 100
    a_usd     = a_inc * AUDUSD if currency == "AUD" else a_inc
    received  = b.get("coupons_received", [])
    total_rcvd = sum(c.get(f'amount_{currency.lower()}', c.get("amount_usd", 0)) for c in received)
    risks_html = "".join(f"<li>{r}</li>" for r in b.get("risks", []))
    if received:
        trows = "".join(f"<tr><td>{c['date']}</td><td>{currency} {c.get(f'amount_{currency.lower()}',0):,.2f}</td><td>{c.get('note','')}</td></tr>" for c in received)
        trows += f'<tr style="font-weight:700"><td>Total</td><td>{currency} {total_rcvd:,.2f}</td><td></td></tr>'
        coupon_html = f'<table class="ct2"><tr><th>Date</th><th>Amount</th><th>Note</th></tr>{trows}</table>'
    else:
        coupon_html = '<div class="ec">No coupons logged yet.</div>'

    return (f'<div class="card">'
            f'<div class="ch"><div>'
            f'<div class="ct">{b["name"]} &nbsp;<span class="badge" style="background:#7c3aed">AT1 BOND</span></div>'
            f'<div class="cm">{b["description"]} · ISIN: {b.get("isin","—")} · {b["issuer"]}</div>'
            f'<div class="cm">Type: {b.get("type","—")} · First call: {b["first_call_date"]} · Purchased: {b["purchase_date"]} @ {b["purchase_price_pct"]}%</div>'
            f'</div></div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:14px">'
            f'<div><div class="il">Notional</div><div class="iv">{currency} {notional:,.0f}</div></div>'
            f'<div><div class="il">Annual coupon</div><div class="iv">{a_pct}% = {currency} {a_inc:,.0f}</div></div>'
            f'<div><div class="il">Annual income (≈ USD)</div><div class="iv" style="color:#16a34a">${a_usd:,.0f}</div></div>'
            f'</div>'
            f'<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;margin-bottom:6px">AT1 Risk Reminders</div>'
            f'<ul class="rk">{risks_html}</ul></div>'
            f'<div class="is"><div style="font-weight:700;font-size:13px;margin-bottom:8px">Coupon Income</div>{coupon_html}</div>'
            f'</div>')

# NYSE market holidays 2025-2027 (Mon-Fri only; observed dates when holiday falls on weekend)
_NYSE_HOLIDAYS = {
    # 2025
    date(2025,  1,  1),  # New Year's Day
    date(2025,  1, 20),  # MLK Day
    date(2025,  2, 17),  # Presidents' Day
    date(2025,  4, 18),  # Good Friday
    date(2025,  5, 26),  # Memorial Day
    date(2025,  6, 19),  # Juneteenth
    date(2025,  7,  4),  # Independence Day
    date(2025,  9,  1),  # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026,  1,  1),  # New Year's Day
    date(2026,  1, 19),  # MLK Day
    date(2026,  2, 16),  # Presidents' Day
    date(2026,  4,  3),  # Good Friday
    date(2026,  5, 25),  # Memorial Day
    date(2026,  6, 19),  # Juneteenth
    date(2026,  7,  3),  # Independence Day (observed; Jul 4 is Saturday)
    date(2026,  9,  7),  # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
    # 2027
    date(2027,  1,  1),  # New Year's Day
    date(2027,  1, 18),  # MLK Day
    date(2027,  2, 15),  # Presidents' Day
    date(2027,  3, 26),  # Good Friday
    date(2027,  5, 31),  # Memorial Day
    date(2027,  6, 18),  # Juneteenth (observed; Jun 19 is Saturday)
    date(2027,  7,  5),  # Independence Day (observed; Jul 4 is Sunday)
    date(2027,  9,  6),  # Labor Day
    date(2027, 11, 25),  # Thanksgiving
    date(2027, 12, 24),  # Christmas (observed; Dec 25 is Saturday)
}

def _is_trading_day(d):
    return d.weekday() < 5 and d not in _NYSE_HOLIDAYS

def _business_days_to_date(start_str, end_str):
    """Count NYSE trading days from start_str up to end_str (or today if earlier)."""
    from datetime import timedelta
    s = date.fromisoformat(start_str)
    e = min(date.fromisoformat(end_str), date.today())
    if e < s:
        return 0
    total = 0
    d = s
    while d <= e:
        if _is_trading_day(d):
            total += 1
        d += timedelta(days=1)
    return total

def _business_days_between(start_str, end_str):
    """Count NYSE trading days between two dates inclusive, NO today cap (for future periods)."""
    from datetime import timedelta
    s = date.fromisoformat(start_str)
    e = date.fromisoformat(end_str)
    if e < s:
        return 0
    total = 0
    d = s
    while d <= e:
        if _is_trading_day(d):
            total += 1
        d += timedelta(days=1)
    return total

def _shares_accumulated(acc):
    """Shares accumulated from start_date to today (capped at end_date).
    If KO'd: accumulation stops at max(ko_date, guaranteed_end) — guaranteed shares still received.
    Returns (total_shares, base_shares, extra_shares, double_up_days_count)."""
    start = acc.get("start_date", "")
    end   = acc.get("end_date", date.today().isoformat())
    g_end = acc.get("guaranteed_end", "")
    spd   = acc.get("shares_per_day", 1)
    if not start:
        return 0, 0, 0, 0
    # If KO'd, cap accumulation at max(ko_date, guaranteed_end)
    ko_log    = _load_ko_log()
    ko_record = ko_log.get(acc.get("id", ""))
    if ko_record:
        ko_date      = ko_record["ko_date"]
        # Still receive guaranteed-period shares even if KO happened before g_end
        effective_end = max(ko_date, g_end) if g_end else ko_date
        end = effective_end
    base      = _business_days_to_date(start, end) * spd
    log       = _load_du_log()
    du_dates  = log.get(acc["id"], {}).get("double_up_dates", [])
    # Only count 2× days within the effective accumulation window
    if ko_record:
        du_dates = [d for d in du_dates if d <= end]
    extra     = len(du_dates) * spd
    return base + extra, base, extra, len(du_dates)

def accum_card(acc, prices, closes=None):
    a  = accumulator_status(acc, prices, closes)
    t  = acc.get("underlying_ticker", "?")

    # ── SETTLED: fully delivered, shares moved to Direct Holdings ────────────
    if a["status"] == "SETTLED":
        ko_record  = a.get("ko_record") or {}
        ko_date    = ko_record.get("ko_date") or KNOWN_KO_EVENTS.get(acc.get("id",""), {}).get("ko_date", "—")
        ko_px      = ko_record.get("ko_price") or KNOWN_KO_EVENTS.get(acc.get("id",""), {}).get("ko_price")
        ko_px_str  = f'${ko_px:,.2f}' if ko_px else "—"
        ko_bar     = acc.get("knockout_price")
        ko_bar_str = f'${ko_bar:,.4f}' if ko_bar else "—"
        sh_del     = acc.get("shares_delivered", "—")
        st_str     = f'${acc.get("strike_price",0):,.4f}' if acc.get("strike_price") else "—"
        cost       = (acc.get("shares_delivered", 0) * acc.get("strike_price", 0)) if acc.get("shares_delivered") else None
        cost_str   = f'${cost:,.2f}' if cost else "—"
        return (f'<div class="card" style="opacity:0.65;border-left:4px solid #94a3b8">'
                f'<div class="ch"><div>'
                f'<div class="ct">{acc.get("name","Accumulator")} &nbsp;'
                f'<span class="badge" style="background:#64748b">✓ SETTLED — shares in Direct Holdings</span></div>'
                f'<div class="cm">{acc.get("underlying_name","—")} ({t}) · {acc.get("issuer","")}</div>'
                f'<div class="cm">{acc.get("start_date","—")} → KO {ko_date} · Strike {st_str} · KO barrier {ko_bar_str}</div>'
                f'</div></div>'
                f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;font-size:12px;color:#64748b">'
                f'<div><div class="il">KO price</div><div class="iv" style="font-size:13px">{ko_px_str}</div></div>'
                f'<div><div class="il">Shares delivered</div><div class="iv" style="font-size:13px">{sh_del}</div></div>'
                f'<div><div class="il">Delivery cost basis</div><div class="iv" style="font-size:13px">{cost_str}</div></div>'
                f'<div><div class="il">Now tracked as</div><div class="iv" style="font-size:13px;color:#2563eb">Direct Holding ({t})</div></div>'
                f'</div></div>')

    STATUS_AC = {
        "KNOCKED_OUT":  ("#22c55e",  "✓ KNOCKED OUT — accumulation stopped"),
        "NEAR_KO":      ("#f97316",  "⚠ ABOVE KO INTRADAY — watch closing price"),
        "GUARANTEED":   ("#3b82f6",  "📅 In guaranteed period"),
        "DOUBLE_UP":    ("#ef4444",  "✖ BELOW STRIKE — 2× leverage active"),
        "ACCUMULATING": ("#f59e0b",  "Accumulating (above strike)"),
        "UNKNOWN":      ("#94a3b8",  "Unknown"),
    }
    sc, sl   = STATUS_AC.get(a["status"], ("#94a3b8","—"))
    pr       = f'${a["current"]:,.2f}' if a["current"] else "—"
    ko_str   = f'${acc.get("knockout_price",0):,.2f}' if acc.get("knockout_price") else "—"
    st_str   = f'${acc.get("strike_price",0):,.2f}'   if acc.get("strike_price")   else "—"
    pko      = (f'{a["current"]/acc["knockout_price"]*100:.1f}% of KO' if (a["current"] and acc.get("knockout_price")) else "—")

    # ── Equity / accumulated position ────────────────────────────────────────
    total_sh, base_sh, extra_sh, du_days = _shares_accumulated(acc)
    strike_px  = acc.get("strike_price")
    current_px = a["current"]
    cost_basis = total_sh * strike_px   if strike_px  else None
    mkt_val    = total_sh * current_px  if current_px else None
    pl         = mkt_val - cost_basis   if (mkt_val is not None and cost_basis is not None) else None
    pl_pct     = pl / cost_basis * 100  if (pl is not None and cost_basis) else None
    pl_clr     = "#16a34a" if (pl is not None and pl >= 0) else "#dc2626"
    pl_str     = (f'{"+" if pl >= 0 else ""}${pl:,.0f} ({pl_pct:+.1f}%)' if (pl is not None and pl_pct is not None) else "—")
    mv_str     = f'${mkt_val:,.0f}' if mkt_val is not None else "—"
    cb_str     = f'${cost_basis:,.0f}' if cost_basis is not None else "—"
    du_note    = (f' <span style="color:#ef4444;font-size:11px">(incl. {extra_sh} extra from {du_days} below-strike day{"s" if du_days!=1 else ""})</span>'
                  if du_days > 0 else "")

    # Label changes based on status
    ko_record  = a.get("ko_record") or {}
    ko_date    = ko_record.get("ko_date", "—")
    ko_px      = ko_record.get("ko_price")
    ko_px_str  = f'${ko_px:,.2f}' if ko_px else "—"
    g_end_acc  = acc.get("guaranteed_end", "")
    today_str  = date.today().isoformat()
    still_in_g = bool(g_end_acc and today_str <= g_end_acc)

    if a["status"] == "KNOCKED_OUT":
        ko_info = (f'<div style="margin-bottom:10px;padding:8px 12px;background:#f0fdf4;'
                   f'border:1px solid #bbf7d0;border-radius:7px;font-size:12px;color:#15803d">'
                   f'🔴 Knocked out on <strong>{ko_date}</strong> at <strong>{ko_px_str}</strong> '
                   f'(barrier {ko_str})'
                   + (f' · Still accumulating through guaranteed period until <strong>{g_end_acc}</strong>'
                      if still_in_g else '') +
                   f'</div>')
        row2 = (f'<div style="margin-top:14px;padding-top:14px;border-top:1px solid #e2e8f0">'
                f'<div style="font-weight:700;font-size:13px;margin-bottom:10px;color:#22c55e">Equity Position</div>'
                f'{ko_info}'
                f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px">'
                f'<div><div class="il">Shares owned</div><div class="iv">{total_sh:,}{du_note}</div></div>'
                f'<div><div class="il">Avg cost (strike)</div><div class="iv">{st_str}</div></div>'
                f'<div><div class="il">Cost basis</div><div class="iv">{cb_str}</div></div>'
                f'<div><div class="il">Market value</div><div class="iv">{mv_str}</div></div>'
                f'</div>'
                f'<div style="margin-top:10px;font-size:15px;font-weight:700;color:{pl_clr}">P&amp;L: {pl_str} &nbsp;<span style="font-size:12px;font-weight:400;color:#64748b">@ {pr} live</span></div>'
                f'</div>')
    else:
        row2 = (f'<div style="margin-top:14px;padding-top:14px;border-top:1px solid #e2e8f0">'
                f'<div style="font-weight:700;font-size:13px;margin-bottom:10px;color:#64748b">Accumulated so far</div>'
                f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px">'
                f'<div><div class="il">Shares so far</div><div class="iv">{total_sh:,}{du_note}</div></div>'
                f'<div><div class="il">Avg cost (strike)</div><div class="iv">{st_str}</div></div>'
                f'<div><div class="il">Cost basis</div><div class="iv">{cb_str}</div></div>'
                f'<div><div class="il">Mkt value</div><div class="iv">{mv_str}</div></div>'
                f'</div>'
                f'<div style="margin-top:10px;font-size:15px;font-weight:700;color:{pl_clr}">Unrealised P&amp;L: {pl_str} &nbsp;<span style="font-size:12px;font-weight:400;color:#64748b">@ {pr} live</span></div>'
                f'</div>')

    return (f'<div class="card">'
            f'<div class="ch"><div>'
            f'<div class="ct">{acc.get("name","Accumulator")} &nbsp;<span class="badge" style="background:{sc}">{sl}</span></div>'
            f'<div class="cm">{acc.get("underlying_name","—")} ({t}) · Strike: {st_str} · Knockout: {ko_str}</div>'
            f'<div class="cm">{acc.get("start_date","—")} → {acc.get("end_date","—")} · Guaranteed until: {acc.get("guaranteed_end","—")}</div>'
            f'</div></div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px">'
            f'<div><div class="il">Current price</div><div class="iv">{pr}</div></div>'
            f'<div><div class="il">vs. KO (close only)</div><div class="iv">{pko}</div></div>'
            f'<div><div class="il">2× leverage below</div><div class="iv" style="color:#dc2626">{st_str}</div></div>'
            f'</div>'
            f'{row2}'
            f'</div>')

def holding_card(h, prices, prev_closes=None):
    ticker   = h.get("ticker", "")
    current  = prices.get(ticker)
    shares   = h.get("shares", 0)
    purchase = h.get("purchase_price", 0)
    cost     = shares * purchase
    mkt_val  = shares * current if current else None
    pl       = mkt_val - cost if mkt_val is not None else None
    pl_pct   = pl / cost * 100 if (pl is not None and cost) else None
    pl_clr   = "#16a34a" if (pl and pl >= 0) else "#dc2626"
    pr_str   = f'${current:,.2f}' if current else "—"
    mv_str   = f'${mkt_val:,.0f}' if mkt_val is not None else "—"
    pl_str   = (f'{"+" if pl >= 0 else ""}${pl:,.0f} ({pl_pct:+.1f}%)' if pl is not None else "—")

    # ── Intraday % change vs previous session close ──────────────────────────
    prev_c  = (prev_closes or {}).get(ticker)
    if current and prev_c and prev_c > 0:
        intra_pct = (current - prev_c) / prev_c * 100
        intra_clr = "#16a34a" if intra_pct >= 0 else "#dc2626"
        intra_arr = "▲" if intra_pct >= 0 else "▼"
        intra_str = f'{intra_arr} {intra_pct:+.2f}% today'
        intra_html = (f'<span style="display:inline-block;margin-left:8px;padding:2px 8px;'
                      f'border-radius:12px;background:{"#f0fdf4" if intra_pct>=0 else "#fef2f2"};'
                      f'color:{intra_clr};font-size:12px;font-weight:700">{intra_str}</span>')
    else:
        intra_html = '<span style="font-size:11px;color:#94a3b8;margin-left:8px">intraday —</span>'

    # ── Dividends received ───────────────────────────────────────────────────────
    divs = h.get("dividends_received", [])
    total_divs = sum(d.get("amount_usd", 0) for d in divs)
    if divs:
        div_chips = ""
        for d in divs:
            dt = d.get("date", "")
            amt = d.get("amount_usd", 0)
            note = d.get("note", "")
            lbl = dt[5:] if len(dt) >= 7 else dt  # show MM-DD
            div_chips += (f'<span title="{note}" style="display:inline-block;margin:2px 3px;padding:3px 9px;'
                          f'border-radius:12px;background:#f0fdf4;color:#16a34a;font-size:11px;'
                          f'font-weight:700;border:1px solid #bbf7d0">'
                          f'{lbl} +${amt:,.2f}</span>')
        div_section = (f'<div style="margin-top:12px;padding-top:10px;border-top:1px solid #f1f5f9">'
                       f'<div style="font-size:11px;color:#64748b;font-weight:600;margin-bottom:4px">'
                       f'DIVIDENDS RECEIVED — Total: <span style="color:#16a34a">${total_divs:,.2f}</span></div>'
                       f'<div>{div_chips}</div></div>')
    else:
        div_section = ""

    return (f'<div class="card">'
            f'<div class="ch"><div>'
            f'<div class="ct"><span class="tick">{ticker}</span>'
            f'<span class="uname">{h.get("name","")}</span>'
            f'{intra_html}</div>'
            f'<div class="cm">ISIN: {h.get("isin","—")} · {shares:g} shares · Purchased @ ${purchase:,.2f}</div>'
            f'</div>'
            f'<div style="text-align:right"><div class="cprice">{pr_str}</div>'
            f'<div class="cpct" style="color:{pl_clr};font-weight:600">{pl_str}</div></div>'
            f'</div>'
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px">'
            f'<div><div class="il">Shares / Units</div><div class="iv">{shares:g}</div></div>'
            f'<div><div class="il">Prev close</div><div class="iv">{f"${prev_c:,.2f}" if prev_c else "—"}</div></div>'
            f'<div><div class="il">Cost basis</div><div class="iv">${cost:,.0f}</div></div>'
            f'<div><div class="il">Market value</div><div class="iv">{mv_str}</div></div>'
            f'</div>'
            f'{div_section}'
            f'</div>')

def build_html(prices, fcn_stats, alerts, live_mode=False, closes=None, prev_closes=None):
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    fcn_cards   = "".join(fcn_card(f, prices) for f in FCN_POSITIONS)
    bond_cards  = "".join(bond_card(b) for b in BOND_POSITIONS)
    active_accums  = [a for a in ACCUMULATOR_POSITIONS if not a.get("settled")]
    settled_accums = [a for a in ACCUMULATOR_POSITIONS if a.get("settled")]
    accum_cards        = "".join(accum_card(a, prices, closes) for a in active_accums)
    settled_accum_cards= "".join(accum_card(a, prices, closes) for a in settled_accums)
    accum_sec     = (f'<div class="sec">Accumulator Positions</div>{accum_cards}' if active_accums else "")
    settled_sec   = (f'<div class="sec" style="color:#94a3b8">Completed Accumulators (shares in Direct Holdings)</div>{settled_accum_cards}'
                     if settled_accums else "")
    holding_cards = "".join(holding_card(h, prices, prev_closes) for h in DIRECT_HOLDINGS)
    holding_sec   = (f'<div class="sec">Direct Holdings (ETFs &amp; Bond Funds)</div>{holding_cards}' if DIRECT_HOLDINGS else "")

    alert_html = ""
    for level, msg in alerts:
        cls = "ab-e" if level == "error" else "ab-w" if level == "warn" else "ab-g"
        alert_html += f'<div class="ab {cls}">{msg}</div>'

    # ── Income summary ──────────────────────────────────────────────────────────
    total_monthly_usd = 0.0
    total_annual_usd  = 0.0
    for f in FCN_POSITIONS:
        n = f.get("notional_usd") or 0
        m = f.get("coupon_monthly_pct") or 0
        a = f.get("coupon_annual_pct") or (m * 12)
        total_monthly_usd += n * m / 100
        total_annual_usd  += n * a / 100
    for b in BOND_POSITIONS:
        inc = b["notional"] * b["coupon_annual_pct"] / 100
        usd = inc * AUDUSD if b["currency"] == "AUD" else inc
        total_annual_usd  += usd
        total_monthly_usd += usd / 12

    total_rcvd = sum(c.get("amount_usd", 0) for f in FCN_POSITIONS for c in f.get("coupons_received", []))
    total_divs_rcvd = sum(d.get("amount_usd", 0) for h in DIRECT_HOLDINGS for d in h.get("dividends_received", []))
    n_safe   = sum(1 for s in fcn_stats if s == "SAFE")
    n_watch  = sum(1 for s in fcn_stats if s == "WATCH")
    n_breach = sum(1 for s in fcn_stats if s == "BREACH")

    # ── Portfolio value & P&L ───────────────────────────────────────────────────
    # FCNs & bonds: held at par (no secondary market price available)
    total_fcn_notional = sum((f.get("notional_usd") or 0) for f in FCN_POSITIONS)
    total_bond_usd = 0.0
    for b in BOND_POSITIONS:
        n   = b.get("notional", 0)
        usd = n * AUDUSD if b.get("currency") == "AUD" else n
        total_bond_usd += usd

    # Accumulators: cost basis = shares × strike; market value = shares × live price
    # NOTE: settled accumulators are excluded here — their shares are already in DIRECT_HOLDINGS
    total_accum_cost = 0.0
    total_accum_mkt  = 0.0
    accum_pl_computable = True
    for acc in ACCUMULATOR_POSITIONS:
        if acc.get("settled"):
            continue  # shares already counted in DIRECT_HOLDINGS — skip to avoid double-count
        a_st = accumulator_status(acc, prices, closes)
        tot_sh, _, _, _ = _shares_accumulated(acc)
        sp   = acc.get("strike_price") or 0
        cp   = a_st.get("current") or 0
        total_accum_cost += tot_sh * sp
        if cp:
            total_accum_mkt += tot_sh * cp
        else:
            accum_pl_computable = False
    total_accum_pl = total_accum_mkt - total_accum_cost if accum_pl_computable else None

    # Direct holdings: cost basis = shares × purchase price; market value = shares × live price
    total_hold_cost = 0.0
    total_hold_mkt  = 0.0
    hold_pl_computable = True
    for h in DIRECT_HOLDINGS:
        cur = prices.get(h.get("ticker", "")) or 0
        sh  = h.get("shares", 0)
        pp  = h.get("purchase_price", 0)
        total_hold_cost += sh * pp
        if cur:
            total_hold_mkt += sh * cur
        else:
            hold_pl_computable = False
    total_hold_pl = total_hold_mkt - total_hold_cost if hold_pl_computable else None

    # Totals
    # Portfolio value = FCN notional (at par) + bond notional (at par) + accum mkt + holdings mkt
    portfolio_value = (total_fcn_notional + total_bond_usd
                       + total_accum_mkt + total_hold_mkt)
    # Unrealised P&L only on the positions we can price (accumulators + direct holdings)
    priceable_cost  = total_accum_cost + total_hold_cost
    priceable_mkt   = total_accum_mkt  + total_hold_mkt
    unrealised_pl   = priceable_mkt - priceable_cost if (accum_pl_computable and hold_pl_computable) else None
    unrealised_pct  = unrealised_pl / priceable_cost * 100 if (unrealised_pl is not None and priceable_cost) else None

    pv_str  = f'${portfolio_value:,.0f}'
    pl_sign = "+" if (unrealised_pl is not None and unrealised_pl >= 0) else ""
    pl_str_portfolio = (f'{pl_sign}${unrealised_pl:,.0f} ({unrealised_pct:+.1f}%)'
                        if unrealised_pl is not None else '—')
    pl_clr_portfolio = "#16a34a" if (unrealised_pl is not None and unrealised_pl >= 0) else "#dc2626"

    # ── Cash position ───────────────────────────────────────────────────────────
    # Deployed = FCN notionals + bond purchase cost (notional × purchase_price_pct/100, USD equiv)
    #            + direct holdings cost basis
    # Accumulators are forward obligations (not upfront cash) — shown separately
    bond_deployed_usd = 0.0
    for b in BOND_POSITIONS:
        n       = b.get("notional", 0)
        pct     = b.get("purchase_price_pct", 100) / 100
        cost    = n * pct
        usd     = cost * AUDUSD if b.get("currency") == "AUD" else cost
        bond_deployed_usd += usd
    # cash_deployed includes:
    #   • FCN notionals (static)
    #   • Bond purchase cost (static)
    #   • Direct holdings cost basis (static — updates when you add/change positions)
    #   • Accumulator shares purchased so far (auto-updates daily; freezes on KO)
    cash_deployed   = total_fcn_notional + bond_deployed_usd + total_hold_cost + total_accum_cost
    available_cash  = CASH_BALANCE_BOS + CASH_SINCE_STATEMENT
    cash_pct_used   = (TOTAL_CASH_DEPOSITED - available_cash) / TOTAL_CASH_DEPOSITED * 100 if TOTAL_CASH_DEPOSITED else 0
    # Remaining accumulator obligation = shares still to be purchased at strike (if no KO)
    # Use _business_days_between for total (no today cap), minus days already done up to today
    from datetime import timedelta as _timedelta
    _tomorrow = (date.today() + _timedelta(days=1)).isoformat()
    accum_future_obligation = sum(
        (
            _business_days_between(_tomorrow, a["end_date"])
            * a.get("shares_per_day", 1) * a.get("strike_price", 0)
        )
        for a in ACCUMULATOR_POSITIONS
        if accumulator_status(a, prices, closes).get("status") not in ("KNOCKED_OUT", "SETTLED")
    )
    cash_clr = "#16a34a" if available_cash >= 0 else "#dc2626"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Investment Tracker – {OWNER}</title>
<style>{CSS}</style></head>
<body>
<div class="hdr">
  <div><h1>{OWNER} — Investment Tracker</h1><div class="sub">{BANK} Portfolio</div></div>
  <div class="ts">Last updated<br><strong>{now}</strong><br>{"<span id='cd' style='opacity:.7;font-size:11px'>Refreshing in <b id='cds'>30</b>s &nbsp;<button onclick='location.reload()' style='font-size:10px;padding:2px 8px;cursor:pointer;border-radius:4px;border:1px solid #aaa;background:#fff'>↻ Now</button></span>" if live_mode else "<span style='opacity:.6;font-size:10px'>Re-run script to refresh prices</span>"}</div>
</div>
<div class="wrap">
  {alert_html}
  <!-- Portfolio overview banner -->
  <div style="background:#fff;border-radius:14px;padding:22px 28px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.09)">
    <div style="font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px">Portfolio Overview</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px">
      <div>
        <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Total Value</div>
        <div style="font-size:26px;font-weight:700;margin-top:4px">{pv_str}</div>
        <div style="font-size:11px;color:#64748b;margin-top:3px">FCNs+Bonds at par · Accum+Holdings live</div>
      </div>
      <div>
        <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Unrealised P&amp;L</div>
        <div style="font-size:26px;font-weight:700;margin-top:4px;color:{pl_clr_portfolio}">{pl_str_portfolio}</div>
        <div style="font-size:11px;color:#64748b;margin-top:3px">Accumulators + direct holdings</div>
      </div>
      <div>
        <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Annual income (est.)</div>
        <div style="font-size:26px;font-weight:700;margin-top:4px;color:#16a34a">${total_annual_usd:,.0f}</div>
        <div style="font-size:11px;color:#64748b;margin-top:3px">${total_monthly_usd:,.0f}/month · FCNs &amp; bonds</div>
      </div>
      <div>
        <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Coupons received</div>
        <div style="font-size:26px;font-weight:700;margin-top:4px">${total_rcvd:,.0f}</div>
        <div style="font-size:11px;color:#64748b;margin-top:3px">FCN coupons logged to date</div>
      </div>
      <div>
        <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Dividends received</div>
        <div style="font-size:26px;font-weight:700;margin-top:4px;color:#16a34a">${total_divs_rcvd:,.0f}</div>
        <div style="font-size:11px;color:#64748b;margin-top:3px">ETF &amp; fund distributions to date</div>
      </div>
    </div>
    <!-- Cash position row -->
    <div style="margin-top:18px;padding-top:16px;border-top:1px solid #f1f5f9">
      <div style="font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px">Cash Position</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:20px">
        <div>
          <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Total deposited</div>
          <div style="font-size:20px;font-weight:700;margin-top:3px">${TOTAL_CASH_DEPOSITED:,.0f}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">15 SWIFT transfers</div>
        </div>
        <div>
          <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Deployed in positions</div>
          <div style="font-size:20px;font-weight:700;margin-top:3px">${cash_deployed:,.0f}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">FCNs · AT1 · ETFs &amp; funds ({cash_pct_used:.0f}% of deposits)</div>
        </div>
        <div>
          <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Available cash</div>
          <div style="font-size:20px;font-weight:700;margin-top:3px;color:{cash_clr}">${available_cash:,.0f}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">BOS {CASH_BALANCE_DATE}{f" · {len(TRADES_SINCE_STATEMENT)} trade(s) since" if TRADES_SINCE_STATEMENT else ""}</div>
        </div>
        <div>
          <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">Remaining accum. obligation</div>
          <div style="font-size:20px;font-weight:700;margin-top:3px;color:#f59e0b">${accum_future_obligation:,.0f}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">Shares still to buy at strike · excl. KO'd</div>
        </div>
      </div>
      <!-- Cash bar -->
      <div style="margin-top:14px;background:#f1f5f9;border-radius:6px;height:8px;overflow:hidden">
        <div style="height:100%;width:{min(cash_pct_used,100):.1f}%;background:#3b82f6;border-radius:6px"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:#94a3b8;margin-top:4px">
        <span>Deployed {cash_pct_used:.0f}%</span><span>Available {100-cash_pct_used:.0f}%</span>
      </div>
    </div>
    <!-- Asset breakdown -->
    <div style="margin-top:14px;padding-top:14px;border-top:1px solid #f1f5f9;display:grid;grid-template-columns:repeat(4,1fr);gap:12px;font-size:12px;color:#64748b">
      <div><span style="font-weight:600;color:#334155">FCNs</span> &nbsp;${total_fcn_notional:,.0f} notional</div>
      <div><span style="font-weight:600;color:#334155">Bonds/AT1</span> &nbsp;${bond_deployed_usd:,.0f} deployed</div>
      <div><span style="font-weight:600;color:#334155">Accumulators</span> &nbsp;deployed ${total_accum_cost:,.0f} (shares×strike) → mkt ${total_accum_mkt:,.0f}</div>
      <div><span style="font-weight:600;color:#334155">Direct holdings</span> &nbsp;cost ${total_hold_cost:,.0f} → mkt ${total_hold_mkt:,.0f}</div>
    </div>
  </div>
  <!-- FCN stats row -->
  <div class="sg">
    <div class="sc"><div class="sl">FCN Positions</div>
      <div class="sv">{len(FCN_POSITIONS)}</div>
      <div class="ss">{n_safe} safe · {n_watch} watch · {n_breach} breach</div></div>
    <div class="sc"><div class="sl">Accumulator positions</div>
      <div class="sv">{len(active_accums)}</div>
      <div class="ss">Active · {len(settled_accums)} settled</div></div>
    <div class="sc"><div class="sl">Bond / AT1 positions</div>
      <div class="sv">{len(BOND_POSITIONS)}</div>
      <div class="ss">Fixed income</div></div>
    <div class="sc"><div class="sl">Direct holdings</div>
      <div class="sv">{len(DIRECT_HOLDINGS)}</div>
      <div class="ss">ETFs &amp; bond funds</div></div>
  </div>
  <div class="sec">Fixed Coupon Note (FCN) Positions</div>
  {fcn_cards}
  <div class="sec">Bond & AT1 Positions</div>
  {bond_cards}
  {accum_sec}
  {holding_sec}
  {settled_sec}
</div>
<footer>Generated {now} · Live prices via Yahoo Finance{"" if not live_mode else " · Auto-refreshing every 30s"}</footer>
{"<script>(function(){{var m=location.hash.match(/#sy=([0-9]+)/);if(m){{var sy=+m[1];history.replaceState(null,'',location.pathname);setTimeout(function(){{window.scrollTo(0,sy);}},80);}}var s=30,el=document.getElementById('cds');var iv=setInterval(function(){{s--;if(!el)el=document.getElementById('cds');if(el)el.textContent=s;if(s<=0){{clearInterval(iv);history.replaceState(null,'','#sy='+Math.round(window.scrollY));location.reload();}}}},1000);}})();</script>" if live_mode else ""}
</body></html>"""

# ═════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _all_tickers():
    """Return tickers for live yfinance fetch. Skips manual_price_only holdings."""
    tickers = []
    for f in FCN_POSITIONS:
        tickers.extend(u["ticker"] for u in f.get("underlyings", []))
    for a in ACCUMULATOR_POSITIONS:
        if a.get("underlying_ticker"):
            tickers.append(a["underlying_ticker"])
    for h in DIRECT_HOLDINGS:
        if h.get("ticker") and not h.get("manual_price_only"):
            tickers.append(h["ticker"])
    return list(dict.fromkeys(tickers))

def _merge_manual_prices(prices: dict) -> dict:
    """Re-inject any MANUAL_PRICES entries not in the live-fetched dict.
    This ensures manual_price_only holdings (e.g. bond fund NAVs keyed by
    ISIN) survive every cache refresh and are never dropped."""
    for k, v in MANUAL_PRICES.items():
        if k not in prices:
            prices[k] = v
    return prices

def _fetch_with_fallback(tickers):
    """Returns (prices, prev_closes) — prev_closes maps ticker → previous session close."""
    try:
        prices, prev_closes = fetch_prices(tickers)
    except Exception as e:
        print(f"  ⚠ yfinance error ({e}), falling back to manual prices")
        prices, prev_closes = {}, {}
    missing = [t for t in tickers if t not in prices]
    if missing:
        filled = {t: MANUAL_PRICES[t] for t in missing if t in MANUAL_PRICES}
        if filled:
            src = "manual prices" if not prices else f"manual fallback for {', '.join(filled)}"
            print(f"  📋 Using {src} (as of {MANUAL_PRICES_DATE})")
        prices.update(filled)
    # Try live fund NAVs (Man Group + Polar Capital) — overwrite manual prices if successful
    fund_navs = _fetch_man_fund_navs()
    if fund_navs:
        prices.update(fund_navs)
    else:
        # Always re-merge manual-only prices (bond funds etc.) after every fetch
        _merge_manual_prices(prices)
    return prices, prev_closes

def _compute_alerts(prices, closes=None):
    alerts    = []
    fcn_stats = []
    for f in FCN_POSITIONS:
        us = [underlying_status(u, prices) for u in f.get("underlyings", [])]
        if "BREACH" in [u["status"] for u in us]:
            st = "BREACH"
            alerts.append(("error", f"🔴 KI BREACH: {f['name']} — one or more underlyings below knock-in level!"))
        elif "WATCH" in [u["status"] for u in us]:
            st = "WATCH"
            alerts.append(("warn", f"⚠ APPROACHING KI: {f['name']} — an underlying is within 20% of knock-in."))
        elif "SAFE" in [u["status"] for u in us]:
            st = "SAFE"
        else:
            st = "UNKNOWN"
        fcn_stats.append(st)
    for a in ACCUMULATOR_POSITIONS:
        s = accumulator_status(a, prices, closes)
        if s["status"] == "DOUBLE_UP":
            alerts.append(("error", f'🔴 2× LEVERAGE: {a.get("name","Accumulator")} — {a.get("underlying_ticker")} is BELOW strike price!'))
        elif s["status"] == "KNOCKED_OUT":
            alerts.append(("info", f'✓ KNOCKED OUT: {a.get("name","Accumulator")} — closing price confirmed KO barrier breached.'))
        elif s["status"] == "NEAR_KO":
            alerts.append(("warn", f'⚠ ABOVE KO INTRADAY: {a.get("name","Accumulator")} — {a.get("underlying_ticker")} is above KO barrier intraday. KO confirmed only at market close.'))
    if not alerts:
        alerts.append(("info", "✓ All clear — no barrier breaches detected across all positions."))
    return fcn_stats, alerts

# ═════════════════════════════════════════════════════════════════════════════
#  LIVE SERVER  (default mode)
# ═════════════════════════════════════════════════════════════════════════════

_price_cache      = {"prices": {}, "ts": 0.0}
_close_cache      = {"closes": {}, "ts": 0.0}   # last confirmed daily closes (for KO check)
_prev_close_cache = {"closes": {}, "ts": 0.0}   # previous session close (for intraday % change)
_cache_lock       = threading.Lock()
CACHE_TTL_SEC = 30
CLOSE_TTL_SEC = 300  # refresh closing prices every 5 min (they only change at market close)

_accum_tickers = list({a["underlying_ticker"] for a in ACCUMULATOR_POSITIONS})

def _background_refresh(tickers, interval=30):
    """Silently refresh prices every `interval` seconds in a background thread.
    HTTP requests always return from cache instantly — no browser timeouts.
    Uses .update() (merge) not full replacement so manual-only entries
    (e.g. bond fund ISINs) seeded at startup are never evicted."""
    close_last = 0.0
    while True:
        try:
            time.sleep(interval)
            print(f"📡 [{datetime.now().strftime('%H:%M:%S')}] Refreshing prices...")
            p, pc = _fetch_with_fallback(tickers)
            with _cache_lock:
                _price_cache["prices"].update(p)    # merge, not replace
                _price_cache["ts"]      = time.time()
                _prev_close_cache["closes"].update(pc)
                _prev_close_cache["ts"] = time.time()
            print(f"   ✓ Done")
            # Refresh closing prices every 5 min (used for accumulator KO checks)
            if time.time() - close_last > CLOSE_TTL_SEC:
                c, cdates = fetch_close_prices(_accum_tickers)
                with _cache_lock:
                    _close_cache["closes"].update(c)
                    _close_cache["ts"] = time.time()
                _update_ko_log(c, cdates)   # permanent KO check first
                _update_du_log(c, cdates)   # then log any new 2× days
                close_last = time.time()
        except Exception as e:
            print(f"  ⚠ Background refresh error: {e}")

def _cached_prices():
    """Return cached prices instantly (never blocks on network)."""
    with _cache_lock:
        return dict(_price_cache["prices"])

def _cached_closes():
    """Return cached daily closing prices (for accumulator KO checks)."""
    with _cache_lock:
        return dict(_close_cache["closes"])

def _cached_prev_closes():
    """Return cached previous-session closes (for intraday % change on holding cards)."""
    with _cache_lock:
        return dict(_prev_close_cache["closes"])

class _Handler(BaseHTTPRequestHandler):
    def _check_auth(self):
        """Return True if request has valid Basic Auth credentials."""
        import base64
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, _, pwd = decoded.partition(":")
            return user == DASHBOARD_USER and pwd == DASHBOARD_PASSWORD
        except Exception:
            return False

    def _require_auth(self):
        """Send 401 and return False so caller can bail out."""
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ALPA Portfolio"')
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Unauthorised")
        return False

    def do_GET(self):
        if not self._check_auth():
            self._require_auth(); return

        if self.path == "/favicon.ico":
            self.send_response(204); self.end_headers(); return

        # /debug — dump live price cache as JSON (diagnostic endpoint)
        if self.path == "/debug":
            import json as _json
            prices = _cached_prices()
            body = _json.dumps({"ts": _price_cache["ts"], "prices": prices}, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path != "/":
            self.send_response(404); self.end_headers(); return

        prices            = _cached_prices()
        closes            = _cached_closes()
        prev_closes       = _cached_prev_closes()
        fcn_stats, alerts = _compute_alerts(prices, closes)
        html              = build_html(prices, fcn_stats, alerts, live_mode=True, closes=closes, prev_closes=prev_closes)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, fmt, *args):
        pass  # silence request logs

def serve(port=None, open_browser=True):
    port = port or int(os.environ.get("PORT", 8765))
    print(f"\n{'═'*52}")
    print(f"  Investment Tracker — {OWNER}  [LIVE MODE]")
    print(f"{'═'*52}")
    print(f"  🌐  http://0.0.0.0:{port}")
    print(f"  📡  Prices refresh every {CACHE_TTL_SEC}s automatically")
    print(f"  ⌨   Press Ctrl+C to stop\n")

    # Seed cache with manual prices instantly so server is responsive immediately
    with _cache_lock:
        _price_cache["prices"] = dict(MANUAL_PRICES)
        _price_cache["ts"]     = time.time()
    print(f"   ✓ Server starting (manual prices loaded, live fetch in background)\n")

    tickers = _all_tickers()

    # Fetch live prices AND closing prices in a background thread
    def _initial_live_fetch():
        print(f"📡 [{datetime.now().strftime('%H:%M:%S')}] Fetching live prices...")
        p, pc = _fetch_with_fallback(tickers)
        with _cache_lock:
            _price_cache["prices"].update(p)        # merge into manual-seeded cache
            _price_cache["ts"]      = time.time()
            _prev_close_cache["closes"].update(pc)
            _prev_close_cache["ts"] = time.time()
        print(f"   ✓ Live prices loaded — {len(p)} tickers")
        # Also fetch closing prices for accumulator KO checks + 2× logging
        c, cdates = fetch_close_prices(_accum_tickers)
        with _cache_lock:
            _close_cache["closes"].update(c)
            _close_cache["ts"] = time.time()
        _update_ko_log(c, cdates)
        _update_du_log(c, cdates)
        print(f"   ✓ Close prices loaded — {c}")

    init_t = threading.Thread(target=_initial_live_fetch, daemon=True)
    init_t.start()

    # Background refresh every 30s
    bg = threading.Thread(target=_background_refresh, args=(tickers, CACHE_TTL_SEC), daemon=True)
    bg.start()

    if open_browser:
        webbrowser.open(f"http://localhost:{port}")
    server = HTTPServer(("0.0.0.0", port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")

# ═════════════════════════════════════════════════════════════════════════════
#  ONCE MODE  (--once flag: generate static HTML file and exit)
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{'═'*52}")
    print(f"  Investment Tracker — {OWNER}  [FILE MODE]")
    print(f"{'═'*52}\n")

    prices, prev_closes = _fetch_with_fallback(_all_tickers())
    closes, cdates      = fetch_close_prices(_accum_tickers)
    _update_ko_log(closes, cdates)
    _update_du_log(closes, cdates)
    fcn_stats, alerts   = _compute_alerts(prices, closes)
    print(f"\n  Prices: {prices}\n")

    html = build_html(prices, fcn_stats, alerts, live_mode=False, closes=closes, prev_closes=prev_closes)
    out  = Path(__file__).parent / "investment_dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard saved: {out}")
    webbrowser.open(out.as_uri())

if __name__ == "__main__":
    if "--once" in sys.argv:
        main()                              # generate static file and open it
    elif "--background" in sys.argv:
        serve(open_browser=False)           # silent background service (no auto-open)
    else:
        # Don't try to open a browser when running on a remote server (Render sets PORT)
        on_server = "PORT" in os.environ
        serve(open_browser=not on_server)   # start live web server
