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
AUDUSD = 0.705  # AUD → USD rate (updated Jun 2026)

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
            # Add entries like: {"date": "2026-07-17", "amount_usd": 1938.75, "note": "Period 1"}
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
        "coupons_received": [],
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
        "coupons_received": [],
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
        "coupons_received": [],
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
        "coupons_received": [],
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
        "coupons_received": [],
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
        "shares": 990,
        "purchase_price": 102.0806,
        "currency": "USD",
        "manual_price_only": True,
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
    # SPY Accumulator — purchased 11 Jun 2026
    # ⚠ Strike and KO prices not yet received — update when term sheet arrives
    {
        "id": "spy_accumulator",
        "name": "SPY Accumulator",
        "issuer": "BOS",
        "underlying_ticker": "SPY",
        "underlying_name": "SPDR S&P 500 ETF",
        "start_date": "2026-06-11",
        "end_date": "2028-06-11",           # assumed 24-month tenor
        "strike_price": None,               # ⚠ Awaiting term sheet
        "knockout_price": None,             # ⚠ Awaiting term sheet
        "guaranteed_end": "2026-06-25",     # 2 weeks guaranteed (≈ 25 Jun 2026)
        "shares_per_day": 1,
        "leverage_below_strike": 2,
    },
    # GOOGL Accumulator — purchased 11 Jun 2026
    # ⚠ Strike and KO prices not yet received — update when term sheet arrives
    {
        "id": "googl_accumulator",
        "name": "GOOGL Accumulator",
        "issuer": "BOS",
        "underlying_ticker": "GOOGL",
        "underlying_name": "Alphabet (Google)",
        "start_date": "2026-06-11",
        "end_date": "2028-06-11",           # assumed 24-month tenor
        "strike_price": None,               # ⚠ Awaiting term sheet
        "knockout_price": None,             # ⚠ Awaiting term sheet
        "guaranteed_end": "2026-08-06",     # 8 weeks guaranteed (≈ 6 Aug 2026)
        "shares_per_day": 1,
        "leverage_below_strike": 2,
    },
]

# ═════════════════════════════════════════════════════════════════════════════
#  MANUAL PRICE FALLBACK  (updated 2026-06-10 via web search)
#  These are used automatically if yfinance cannot connect.
# ═════════════════════════════════════════════════════════════════════════════

MANUAL_PRICES = {
    # USD ETFs
    "SPY":   725.43,
    "QQQ":   693.69,
    "DIA":   500.25,
    # US Tech
    "META":  570.98,
    "GOOGL": 356.38,
    "NVDA":  200.42,
    # Semiconductors
    "INTC":  107.04,
    "TSM":   408.75,
    "ASML":  1734.19,
    # Industrials (USD)
    "HON":   205.88,
    # US Banks
    "GS":    1001.29,
    "JPM":   309.14,
    "MS":    206.66,
    # Asia ETFs
    "EWY":   179.00,
    "EWJ":   90.98,
    "CQQQ":  54.00,
    # Direct ETF holdings
    "GLD":   397.27,
    "OIH":   429.81,
    # Bond funds (Man Group) — update NAV from each BOS statement
    "IE00039W6MB8": 101.15,   # Man Dynamic Income — NAV USD (BOS 31 May 2026)
    "IE000KEXCUV1": 113.08,   # Man Global InvGrade Opps — NAV USD (BOS 31 May 2026)
    # European (local currency)
    "HSBA.L":  1329.20,   # GBp
    "GLE.PA":  69.87,     # EUR
    "UBS":     46.77,     # USD (NYSE) — confirmed ticker from GS term sheet
    "SU.PA":   261.50,    # EUR
    "SIE.DE":  279.10,    # EUR — confirmed from HSBC term sheet
}
MANUAL_PRICES_DATE = "2026-06-11"

# ═════════════════════════════════════════════════════════════════════════════
#  PRICE FETCHING
# ═════════════════════════════════════════════════════════════════════════════

def fetch_prices(tickers: list) -> dict:
    prices = {}
    if not tickers:
        return prices
    print(f"📡 Fetching live prices: {', '.join(tickers)}")
    for t in tickers:
        try:
            obj  = yf.Ticker(t)
            p    = obj.fast_info.last_price
            if p and float(p) > 0:
                prices[t] = round(float(p), 4)
            else:
                hist = obj.history(period="2d")
                if not hist.empty:
                    prices[t] = round(float(hist["Close"].iloc[-1]), 4)
                else:
                    print(f"  ⚠ {t}: no price data")
        except Exception as e:
            print(f"  ⚠ {t}: {e}")
    return prices

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

def accumulator_status(acc: dict, prices: dict) -> dict:
    t       = acc.get("underlying_ticker", "")
    current = prices.get(t)
    strike  = acc.get("strike_price")
    ko      = acc.get("knockout_price")
    g_end   = acc.get("guaranteed_end")
    today   = date.today().isoformat()

    knocked_out    = bool(current and ko and current >= ko)
    in_guaranteed  = bool(g_end and today <= g_end)
    below_strike   = bool(current and strike and current < strike)

    if knocked_out:          status = "KNOCKED_OUT"
    elif in_guaranteed:      status = "GUARANTEED"
    elif below_strike:       status = "DOUBLE_UP"
    elif current:            status = "ACCUMULATING"
    else:                    status = "UNKNOWN"

    return {**acc, "current": current, "status": status,
            "knocked_out": knocked_out, "in_guaranteed": in_guaranteed, "below_strike": below_strike}

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

    # Coupon table
    if received:
        trows = "".join(f"<tr><td>{c['date']}</td><td>${c.get('amount_usd',0):,.2f}</td><td>{c.get('note','')}</td></tr>" for c in received)
        trows += f'<tr style="font-weight:700"><td>Total</td><td>${total_rcvd:,.2f}</td><td></td></tr>'
        coupon_html = f'<table class="ct2"><tr><th>Date</th><th>Amount (USD)</th><th>Note</th></tr>{trows}</table>'
    else:
        coupon_html = '<div class="ec">No coupons logged yet — add entries to coupons_received in the config.</div>'

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

def accum_card(acc, prices):
    a = accumulator_status(acc, prices)
    t = acc.get("underlying_ticker", "?")
    STATUS_AC = {
        "KNOCKED_OUT":  ("#22c55e",  "✓ KNOCKED OUT — accumulation stopped"),
        "GUARANTEED":   ("#3b82f6",  "📅 In guaranteed period"),
        "DOUBLE_UP":    ("#ef4444",  "✖ BELOW STRIKE — 2× leverage active"),
        "ACCUMULATING": ("#f59e0b",  "Accumulating (above strike)"),
        "UNKNOWN":      ("#94a3b8",  "Unknown"),
    }
    sc, sl = STATUS_AC.get(a["status"], ("#94a3b8","—"))
    pr  = f'${a["current"]:,.2f}' if a["current"] else "—"
    ko  = f'${acc.get("knockout_price",0):,.2f}' if acc.get("knockout_price") else "—"
    st  = f'${acc.get("strike_price",0):,.2f}'   if acc.get("strike_price")   else "—"
    pko = (f'{a["current"]/acc["knockout_price"]*100:.1f}% of KO' if (a["current"] and acc.get("knockout_price")) else "—")

    return (f'<div class="card">'
            f'<div class="ch"><div>'
            f'<div class="ct">{acc.get("name","Accumulator")} &nbsp;<span class="badge" style="background:{sc}">{sl}</span></div>'
            f'<div class="cm">{acc.get("underlying_name","—")} ({t}) · Strike: {st} · Knockout: {ko}</div>'
            f'<div class="cm">{acc.get("start_date","—")} → {acc.get("end_date","—")} · Guaranteed until: {acc.get("guaranteed_end","—")}</div>'
            f'</div></div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px">'
            f'<div><div class="il">Current price</div><div class="iv">{pr}</div></div>'
            f'<div><div class="il">vs. Knockout</div><div class="iv">{pko}</div></div>'
            f'<div><div class="il">2× leverage below</div><div class="iv" style="color:#dc2626">{st}</div></div>'
            f'</div></div>')

def holding_card(h, prices):
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
    return (f'<div class="card">'
            f'<div class="ch"><div>'
            f'<div class="ct"><span class="tick">{ticker}</span>'
            f'<span class="uname">{h.get("name","")}</span></div>'
            f'<div class="cm">ISIN: {h.get("isin","—")} · {shares} shares · Purchased @ ${purchase:,.2f}</div>'
            f'</div>'
            f'<div style="text-align:right"><div class="cprice">{pr_str}</div>'
            f'<div class="cpct" style="color:{pl_clr};font-weight:600">{pl_str}</div></div>'
            f'</div>'
            f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px">'
            f'<div><div class="il">Shares</div><div class="iv">{shares}</div></div>'
            f'<div><div class="il">Cost basis</div><div class="iv">${cost:,.0f}</div></div>'
            f'<div><div class="il">Market value</div><div class="iv">{mv_str}</div></div>'
            f'</div></div>')

def build_html(prices, fcn_stats, alerts, live_mode=False):
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    fcn_cards   = "".join(fcn_card(f, prices) for f in FCN_POSITIONS)
    bond_cards  = "".join(bond_card(b) for b in BOND_POSITIONS)
    accum_cards   = "".join(accum_card(a, prices) for a in ACCUMULATOR_POSITIONS)
    accum_sec     = (f'<div class="sec">Accumulator Positions</div>{accum_cards}' if ACCUMULATOR_POSITIONS else "")
    holding_cards = "".join(holding_card(h, prices) for h in DIRECT_HOLDINGS)
    holding_sec   = (f'<div class="sec">Direct Holdings (ETFs &amp; Bond Funds)</div>{holding_cards}' if DIRECT_HOLDINGS else "")

    alert_html = ""
    for level, msg in alerts:
        cls = "ab-e" if level == "error" else "ab-w" if level == "warn" else "ab-g"
        alert_html += f'<div class="ab {cls}">{msg}</div>'

    # Summary stats
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
    n_safe   = sum(1 for s in fcn_stats if s == "SAFE")
    n_watch  = sum(1 for s in fcn_stats if s == "WATCH")
    n_breach = sum(1 for s in fcn_stats if s == "BREACH")

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
  <div class="sg">
    <div class="sc"><div class="sl">FCN Positions</div>
      <div class="sv">{len(FCN_POSITIONS)}</div>
      <div class="ss">{n_safe} safe · {n_watch} watch · {n_breach} breach</div></div>
    <div class="sc"><div class="sl">Monthly income (est.)</div>
      <div class="sv" style="color:#16a34a">${total_monthly_usd:,.0f}</div>
      <div class="ss">USD equivalent</div></div>
    <div class="sc"><div class="sl">Annual income (est.)</div>
      <div class="sv" style="color:#16a34a">${total_annual_usd:,.0f}</div>
      <div class="ss">USD equivalent</div></div>
    <div class="sc"><div class="sl">Total received</div>
      <div class="sv">${total_rcvd:,.0f}</div>
      <div class="ss">FCN coupons logged</div></div>
  </div>
  <div class="sec">Fixed Coupon Note (FCN) Positions</div>
  {fcn_cards}
  <div class="sec">Bond & AT1 Positions</div>
  {bond_cards}
  {accum_sec}
  {holding_sec}
</div>
<footer>Generated {now} · Live prices via Yahoo Finance{"" if not live_mode else " · Auto-refreshing every 30s"}</footer>
{"<script>(function(){{let s=30;const el=document.getElementById('cds');const iv=setInterval(()=>{{s--;if(el)el.textContent=s;if(s<=0){{clearInterval(iv);location.reload();}}}},1000);}})();</script>" if live_mode else ""}
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
    try:
        prices = fetch_prices(tickers)
    except Exception as e:
        print(f"  ⚠ yfinance error ({e}), falling back to manual prices")
        prices = {}
    missing = [t for t in tickers if t not in prices]
    if missing:
        filled = {t: MANUAL_PRICES[t] for t in missing if t in MANUAL_PRICES}
        if filled:
            src = "manual prices" if not prices else f"manual fallback for {', '.join(filled)}"
            print(f"  📋 Using {src} (as of {MANUAL_PRICES_DATE})")
        prices.update(filled)
    # Always re-merge manual-only prices (bond funds etc.) after every fetch
    _merge_manual_prices(prices)
    return prices

def _compute_alerts(prices):
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
        s = accumulator_status(a, prices)
        if s["status"] == "DOUBLE_UP":
            alerts.append(("error", f'🔴 2× LEVERAGE: {a.get("name","Accumulator")} — {a.get("underlying_ticker")} is BELOW strike price!'))
        elif s["status"] == "KNOCKED_OUT":
            alerts.append(("info", f'✓ KNOCKED OUT: {a.get("name","Accumulator")} — accumulation has stopped.'))
    if not alerts:
        alerts.append(("info", "✓ All clear — no barrier breaches detected across all positions."))
    return fcn_stats, alerts

# ═════════════════════════════════════════════════════════════════════════════
#  LIVE SERVER  (default mode)
# ═════════════════════════════════════════════════════════════════════════════

_price_cache  = {"prices": {}, "ts": 0.0}
_cache_lock   = threading.Lock()
CACHE_TTL_SEC = 30

def _background_refresh(tickers, interval=30):
    """Silently refresh prices every `interval` seconds in a background thread.
    HTTP requests always return from cache instantly — no browser timeouts.
    Uses .update() (merge) not full replacement so manual-only entries
    (e.g. bond fund ISINs) seeded at startup are never evicted."""
    while True:
        try:
            time.sleep(interval)
            print(f"📡 [{datetime.now().strftime('%H:%M:%S')}] Refreshing prices...")
            p = _fetch_with_fallback(tickers)
            with _cache_lock:
                _price_cache["prices"].update(p)   # merge, not replace
                _price_cache["ts"]     = time.time()
            print(f"   ✓ Done")
        except Exception as e:
            print(f"  ⚠ Background refresh error: {e}")

def _cached_prices():
    """Return cached prices instantly (never blocks on network)."""
    with _cache_lock:
        return dict(_price_cache["prices"])

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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
        fcn_stats, alerts = _compute_alerts(prices)
        html              = build_html(prices, fcn_stats, alerts, live_mode=True)

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

    # Fetch live prices in a background thread — server stays responsive during fetch
    def _initial_live_fetch():
        print(f"📡 [{datetime.now().strftime('%H:%M:%S')}] Fetching live prices...")
        p = _fetch_with_fallback(tickers)
        with _cache_lock:
            _price_cache["prices"].update(p)   # merge into manual-seeded cache
            _price_cache["ts"]     = time.time()
        print(f"   ✓ Live prices loaded — {len(p)} tickers")

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

    prices            = _fetch_with_fallback(_all_tickers())
    fcn_stats, alerts = _compute_alerts(prices)
    print(f"\n  Prices: {prices}\n")

    html = build_html(prices, fcn_stats, alerts, live_mode=False)
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
