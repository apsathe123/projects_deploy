"""
India-specific investment reference data.
Asset allocations, instrument recommendations, and return assumptions
as of 2026. Based on Indian market conditions and available instruments.

Used by engine.py to produce India-specific financial plans.
"""

LAST_UPDATED = "2026-04-18"
DATA_EFFECTIVE_FROM = "2026-04-01"
DATA_SOURCES = [
    "DEA small savings notification dated 2026-03-30 for Q1 FY 2026-27 rates.",
    "RBI SGB 2023-24 notification dated 2023-12-11; no fresh SGB tranche is assumed.",
    "Income Tax India capital gains references reflecting Finance (No. 2) Act, 2024 changes.",
]

INFLATION_INDIA = 0.055  # 5.5% long-run nominal inflation assumption (RBI target band 4±2%)

# ── Expected returns by asset class (nominal CAGR, India) ─────────────────────
# Based on 15–20 year historical data; forward-looking estimates are conservative.
RETURN_ASSUMPTIONS = {
    "equity_largecap_index":   0.110,   # Nifty 50 index fund
    "equity_nextfifty_index":  0.120,   # Nifty Next 50 index fund
    "equity_midcap_index":     0.130,   # Nifty Midcap 150 index fund
    "equity_smallcap_index":   0.140,   # Nifty Smallcap 250 — high volatility
    "equity_flexicap":         0.120,   # Flexi-cap / multi-cap fund
    "equity_elss":             0.120,   # ELSS (same as flexi-cap, 3-year lock-in)
    "equity_arbitrage":        0.065,   # Arbitrage fund (debt-like return, equity taxation)
    "debt_liquid":             0.065,   # Liquid / overnight fund
    "debt_ultrashort":         0.069,   # Ultra-short term fund
    "debt_shortduration":      0.073,   # Short duration fund
    "debt_fd_1yr":             0.068,   # Bank FD 1-year
    "debt_fd_3yr":             0.073,   # Bank FD 3-year
    "debt_ppf":                0.071,   # PPF (tax-free — effective pre-tax ~10% for 30% bracket)
    "debt_nps_mixed":          0.100,   # NPS Tier-1 (50% equity / 50% debt blend)
    "debt_rbi_bond":           0.081,   # RBI Floating Rate Savings Bond
    "debt_vpf":                0.082,   # VPF (same rate as EPF)
    "gold_sgb":                0.090,   # SGB: ~7% price + 2.5% interest (tax-free at maturity)
    "gold_etf":                0.075,   # Gold ETF (price appreciation only)
    "reit":                    0.082,   # Listed REITs (rental yield + appreciation)
}


# ── Time horizon bands ────────────────────────────────────────────────────────
def horizon_band(years: int) -> str:
    if years < 3:
        return "short"
    elif years < 7:
        return "medium"
    elif years < 15:
        return "long"
    else:
        return "vlong"


HORIZON_LABELS = {
    "short":  "Short-term (< 3 years)",
    "medium": "Medium-term (3–7 years)",
    "long":   "Long-term (7–15 years)",
    "vlong":  "Very long-term (15+ years)",
}


# ── Risk profile by age ───────────────────────────────────────────────────────
def suggested_risk_profile(age: int) -> str:
    """Suggest a risk profile based on age as a starting point."""
    if age <= 35:
        return "aggressive"
    elif age <= 50:
        return "moderate"
    else:
        return "conservative"


AGE_RISK_NOTES = {
    "aggressive": (
        "Age ≤ 35: maximum accumulation phase. Time is your most powerful asset — "
        "short-term volatility is recoverable. Prioritise growth."
    ),
    "moderate": (
        "Age 36–50: balance growth with increasing capital protection. "
        "You have time to grow, but major losses are harder to recover from."
    ),
    "conservative": (
        "Age > 50: shift focus to capital preservation and income generation. "
        "Reduce equity exposure progressively as retirement approaches."
    ),
}


# ── Asset allocation table ────────────────────────────────────────────────────
# 4 horizon bands × 3 risk profiles = 12 combinations.
# Allocations: equity, debt, gold, cash (always sum to 1.0).
# Expected return is a blended portfolio CAGR (nominal).
#
# Key design principles:
# - Short-term goals: equity is capped even for aggressive profiles (markets can
#   fall 30–40% in any 1–2 year window; capital preservation dominates).
# - Gold is 5–10% across most portfolios — India has cultural affinity + SGB is
#   a genuinely excellent instrument (tax-free maturity + 2.5% interest).
# - Debt shifts from FD/liquid (short) → PPF/NPS (long) as horizon extends.
# - Cash/liquid is non-zero only for short/medium horizons (opportunity cost).

ALLOCATION_TABLE = {

    # ── Short-term: < 3 years ─────────────────────────────────────────────────
    # Capital preservation is the mandate. Even aggressive investors must prioritise
    # not losing money over a 1–2 year window.
    ("short", "conservative"): {
        "equity": 0.00, "debt": 0.70, "gold": 0.05, "cash": 0.25,
        "return": 0.065,
        "label": "Capital Preservation",
        "rationale": (
            "With < 3 years, equities are off the table — a market correction of 30–40% "
            "could wipe out the entire goal. FDs, liquid funds, and ultra-short debt funds "
            "give you predictable, low-risk returns of 6.5–7.5%."
        ),
    },
    ("short", "moderate"): {
        "equity": 0.10, "debt": 0.65, "gold": 0.05, "cash": 0.20,
        "return": 0.067,
        "label": "Capital Preservation",
        "rationale": (
            "A small equity allocation via arbitrage funds provides equity-taxation treatment "
            "with near-debt returns. Core remains in short-duration debt and FDs."
        ),
    },
    ("short", "aggressive"): {
        "equity": 0.20, "debt": 0.60, "gold": 0.05, "cash": 0.15,
        "return": 0.075,
        "label": "Conservative",
        "rationale": (
            "Even for aggressive investors, equity is capped at 20% for short-term goals. "
            "Use only large-cap index funds for the equity portion. "
            "Increase the timeline if possible to unlock more equity."
        ),
    },

    # ── Medium-term: 3–7 years ────────────────────────────────────────────────
    # Equity starts contributing meaningfully. Gold via SGB makes sense from 5 years.
    # Debt via PPF and short-duration funds for stability.
    ("medium", "conservative"): {
        "equity": 0.30, "debt": 0.55, "gold": 0.10, "cash": 0.05,
        "return": 0.083,
        "label": "Balanced Conservative",
        "rationale": (
            "Equity provides inflation-beating growth; heavy debt allocation provides "
            "stability. PPF and short-duration funds anchor the debt portion. "
            "A 30% equity allocation in a market dip should recover within 3–4 years."
        ),
    },
    ("medium", "moderate"): {
        "equity": 0.50, "debt": 0.35, "gold": 0.10, "cash": 0.05,
        "return": 0.092,
        "label": "Balanced",
        "rationale": (
            "Classic 50/35/10/5 split for medium-term goals. Equity via Nifty 50 + Nifty "
            "Next 50 index funds. Debt via PPF + short duration MF. Gold via SGB if "
            "horizon is 5+ years, else Gold ETF."
        ),
    },
    ("medium", "aggressive"): {
        "equity": 0.65, "debt": 0.25, "gold": 0.10, "cash": 0.00,
        "return": 0.105,
        "label": "Balanced Growth",
        "rationale": (
            "Higher equity allocation for growth-seekers. At 3–7 years, equity markets "
            "are likely to be higher than today. Nifty 50 + Nifty Next 50 form the core; "
            "a small mid-cap allocation acceptable at 6+ year horizon."
        ),
    },

    # ── Long-term: 7–15 years ─────────────────────────────────────────────────
    # Equity dominates; compounding does the heavy lifting.
    # PPF becomes the cornerstone debt instrument (EEE, consistent 7.1%).
    ("long", "conservative"): {
        "equity": 0.50, "debt": 0.35, "gold": 0.10, "cash": 0.05,
        "return": 0.092,
        "label": "Growth Conservative",
        "rationale": (
            "For risk-averse investors, 50% equity over 7–15 years still delivers "
            "meaningful wealth creation while limiting downside. PPF and debt MFs "
            "provide a stable floor. Gold via SGB (2.5% interest + appreciation)."
        ),
    },
    ("long", "moderate"): {
        "equity": 0.65, "debt": 0.25, "gold": 0.10, "cash": 0.00,
        "return": 0.105,
        "label": "Growth",
        "rationale": (
            "65% equity is the sweet spot for 7–15 year goals. Nifty 50 + Nifty Next 50 "
            "as the core; mid-cap index acceptable (max 20–25% of equity portion). "
            "PPF maxed out annually. SGBs for gold."
        ),
    },
    ("long", "aggressive"): {
        "equity": 0.80, "debt": 0.15, "gold": 0.05, "cash": 0.00,
        "return": 0.111,
        "label": "Aggressive Growth",
        "rationale": (
            "High equity allocation for long horizons. Across 7–15 years, Indian equity "
            "markets have never delivered negative returns (even with multiple crashes). "
            "Diversify across large cap, next 50, and mid cap. PPF for mandatory debt floor."
        ),
    },

    # ── Very long-term: 15+ years ─────────────────────────────────────────────
    # Maximum compounding benefit from equity. NPS adds retirement-specific tax benefits.
    # Debt instruments are largely PPF + NPS (locked, disciplined savings).
    ("vlong", "conservative"): {
        "equity": 0.60, "debt": 0.30, "gold": 0.10, "cash": 0.00,
        "return": 0.100,
        "label": "Growth",
        "rationale": (
            "Even conservative investors should hold 60%+ equity over 15+ years — the "
            "real risk at this horizon is inflation eroding purchasing power, not market "
            "volatility. PPF + NPS as the debt anchor."
        ),
    },
    ("vlong", "moderate"): {
        "equity": 0.75, "debt": 0.20, "gold": 0.05, "cash": 0.00,
        "return": 0.110,
        "label": "Aggressive Growth",
        "rationale": (
            "75% equity over 15+ years is well-suited for most working-age Indians. "
            "Compounding at 11% p.a. doubles money every ~6.5 years. "
            "NPS + PPF covers the debt portion with tax efficiency."
        ),
    },
    ("vlong", "aggressive"): {
        "equity": 0.85, "debt": 0.10, "gold": 0.05, "cash": 0.00,
        "return": 0.120,
        "label": "Aggressive Growth",
        "rationale": (
            "85% equity for very long horizons maximises compounding. Include a small-cap "
            "allocation (max 10% of equity) via SIP only — never lump sum. "
            "NPS Tier-1 covers the remaining debt with excellent tax benefits."
        ),
    },
}


# ── Instrument recommendations by asset class and time horizon ────────────────
# Listed in priority order within each bucket.

EQUITY_INSTRUMENTS = {
    "short": [
        "Arbitrage funds — equity taxation treatment, returns similar to liquid funds (~6.5%); "
        "use only if you have existing equity exposure elsewhere.",
        "Nifty 50 index fund — only if you can accept the risk of a 20–30% short-term loss.",
    ],
    "medium": [
        "Nifty 50 index fund — core holding (UTI Nifty 50, HDFC Nifty 50, Nippon India Nifty 50).",
        "Nifty Next 50 index fund — adds mid-large cap breadth.",
        "Flexi-cap / multi-cap fund — Parag Parikh Flexi Cap, Mirae Asset Large & Midcap.",
        "ELSS fund — qualifies for ₹1.5L 80C deduction; 3-year lock-in aligns with horizon.",
    ],
    "long": [
        "Nifty 50 index fund — core holding (lowest cost, most diversified).",
        "Nifty Next 50 index fund — higher return potential than Nifty 50.",
        "Nifty Midcap 150 index fund — cap at 20–25% of equity portion; higher volatility.",
        "Flexi-cap fund — Parag Parikh Flexi Cap (international diversification + domestic).",
        "ELSS fund — for annual 80C benefit (max ₹1.5L per year).",
    ],
    "vlong": [
        "Nifty 50 index fund — non-negotiable core (50%+ of equity).",
        "Nifty Next 50 index fund — strong long-run outperformance of Nifty 50.",
        "Nifty Midcap 150 index fund — 20–30% of equity for wealth acceleration.",
        "Nifty Smallcap 250 index fund — max 10% of equity, SIP only, accept 40–50% drawdowns.",
        "NPS Tier-1 (Active choice: 75% E / 25% C) — retirement goals only; additional ₹50K 80CCD(1B) deduction.",
        "ELSS fund — for 80C benefit while goals are active.",
    ],
}

DEBT_INSTRUMENTS = {
    "short": [
        "Bank FD (1–3 year, ~6.8–7.3%) — DICGC insured up to ₹5L; predictable, no market risk.",
        "Liquid mutual fund — for amounts needed within 3 months; same-day redemption.",
        "Ultra-short term debt fund — for 3-month to 1-year horizon; ~7%.",
        "Recurring Deposit (RD) — bank or post office; ideal for SIP-style debt accumulation.",
    ],
    "medium": [
        "PPF — max out ₹1.5L/year; 7.1% tax-free; 80C deduction; government-backed.",
        "Short-duration debt mutual fund — ~7–7.5%; more liquid than FD.",
        "RBI Floating Rate Savings Bond — currently 8.05% p.a.; taxable but risk-free.",
        "5-year Bank FD — qualifies for 80C deduction; 6.5–7.5% depending on bank.",
        "Post Office Time Deposit (5-year) — 7.5%; 80C eligible.",
    ],
    "long": [
        "PPF — max out ₹1.5L/year consistently; EEE (exempt-exempt-exempt); best debt instrument for India.",
        "NPS Tier-1 (Corporate Bond or G-Sec allocation) — for retirement goals; extra ₹50K deduction.",
        "Short to medium duration debt mutual fund — for non-locked, flexible debt allocation.",
        "RBI Floating Rate Savings Bond — for lump-sum debt allocation; no market risk.",
    ],
    "vlong": [
        "PPF — consistently max out ₹1.5L/year for full term; the single best fixed-income instrument in India.",
        "NPS Tier-1 — mandatory for retirement goals; equity + debt blend within NPS.",
        "VPF (Voluntary Provident Fund) — if salaried; EPF rate (~8.25%), tax-free.",
        "Medium duration debt MF — for surplus beyond PPF/NPS capacity.",
    ],
}

GOLD_INSTRUMENTS = {
    "short": [
        "Gold ETF (Nippon Gold ETF, SBI Gold ETF) — fully liquid, no lock-in; buy/sell on NSE/BSE.",
    ],
    "medium": [
        "Sovereign Gold Bond (SGB) — best for 5+ year horizon if available through fresh issuance; "
        "otherwise compare secondary-market SGB premiums/discounts with Gold ETFs. Existing SGBs carry "
        "2.5% p.a. interest and capital gains are tax-free at 8-year maturity.",
        "Gold ETF — use if you may need to exit before 5 years; fully liquid.",
    ],
    "long": [
        "Sovereign Gold Bond (SGB) — optimal if fresh issuance is available or secondary-market pricing "
        "is reasonable; 2.5% interest is taxable annually and capital gains are tax-free at maturity.",
        "Gold ETF — for the portion you want to keep liquid (early exit option).",
    ],
    "vlong": [
        "Sovereign Gold Bond (SGB) — use fresh tranches if available; otherwise buy only when secondary-market "
        "pricing is sensible. Reinvest at maturity. The 2.5% interest plus gold appreciation can be attractive, "
        "with capital gains tax-free at maturity.",
    ],
}

CASH_INSTRUMENTS = [
    "High-yield savings account (Yes Bank, HDFC, ICICI, Kotak — 3.5–7% p.a.).",
    "Liquid mutual fund — 6–6.5%; same-day redemption; slightly better than savings account.",
    "Overnight fund — lowest possible risk; park monthly surplus before deploying into goals.",
]


# ── Tax notes ─────────────────────────────────────────────────────────────────
TAX_NOTES = {
    "equity_ltcg": (
        "Equity MF / direct stocks held > 1 year: LTCG taxed at 12.5% on gains above ₹1.25L/year."
    ),
    "equity_stcg": (
        "Equity MF / direct stocks held < 1 year: STCG taxed at 20%."
    ),
    "debt_mf": (
        "Debt MFs (from Apr 2023): gains taxed at income slab rate; no indexation benefit."
    ),
    "ppf": (
        "PPF: EEE treatment — contribution (80C deduction), growth, and withdrawal are all tax-free."
    ),
    "nps": (
        "NPS: 80C (up to ₹1.5L) + additional ₹50K under 80CCD(1B). "
        "At retirement: 60% lump sum is tax-free; 40% must go into annuity (taxable as income)."
    ),
    "elss": (
        "ELSS: 80C deduction up to ₹1.5L; 3-year lock-in; LTCG at 12.5% above ₹1.25L on exit."
    ),
    "sgb": (
        "SGB: 2.5% annual interest is taxable at slab rate. "
        "Capital gains on redemption at maturity (8 years) are fully tax-exempt."
    ),
    "fd": (
        "Bank FD: interest taxed at slab rate; TDS at 10% above ₹40,000/year (₹50K for seniors)."
    ),
    "arbitrage": (
        "Arbitrage funds: treated as equity for taxation — LTCG (>1 year) at 12.5%, STCG (<1 year) at 20%. "
        "In practice, most arbitrage funds generate returns close to liquid fund rates."
    ),
}


# ── Priority framework for Indian investors ───────────────────────────────────
# This is the recommended order in which to address financial priorities.
PRIORITY_ORDER = [
    {
        "rank": 1,
        "name": "Emergency Fund",
        "rule": "3–6 months of expenses in a liquid fund or savings account. Non-negotiable.",
    },
    {
        "rank": 2,
        "name": "Health Insurance",
        "rule": (
            "Minimum ₹10L individual / ₹20L family floater. "
            "A single hospitalisation without insurance can wipe out years of savings."
        ),
    },
    {
        "rank": 3,
        "name": "Life Insurance",
        "rule": (
            "Term plan = 10–15× annual income if you have dependents. "
            "Avoid ULIPs and endowment plans — they are poor investments."
        ),
    },
    {
        "rank": 4,
        "name": "High-interest Debt",
        "rule": (
            "Pay off credit cards (36–40% p.a.) and personal loans (12–24% p.a.) "
            "before investing. No investment reliably beats these rates."
        ),
    },
    {
        "rank": 5,
        "name": "80C & 80CCD Tax Optimisation",
        "rule": (
            "Max out ₹1.5L under 80C (PPF, ELSS, EPF, home loan principal). "
            "Then ₹50K more under 80CCD(1B) via NPS Tier-1. "
            "Tax savings directly boost returns."
        ),
    },
    {
        "rank": 6,
        "name": "Goal-based Investing",
        "rule": (
            "After above foundations are in place, invest per goal allocation. "
            "Prioritise high-priority and shorter-horizon goals first."
        ),
    },
]


# ── Main lookup function ──────────────────────────────────────────────────────
def get_allocation(years: int, risk_profile: str) -> dict:
    """
    Returns India-specific asset allocation dict for a given time horizon and risk profile.
    Includes instrument recommendations for each asset class.

    Args:
        years: Years to goal.
        risk_profile: One of 'conservative', 'moderate', 'aggressive'.

    Returns:
        Dict with keys: equity, debt, gold, cash, return, label, rationale,
        equity_instruments, debt_instruments, gold_instruments, cash_instruments, band.
    """
    band = horizon_band(years)
    risk_profile = risk_profile.lower()
    if risk_profile not in ("conservative", "moderate", "aggressive"):
        risk_profile = "moderate"

    alloc = ALLOCATION_TABLE[(band, risk_profile)].copy()
    alloc["band"] = band
    alloc["equity_instruments"] = EQUITY_INSTRUMENTS[band]
    alloc["debt_instruments"] = DEBT_INSTRUMENTS[band]
    alloc["gold_instruments"] = GOLD_INSTRUMENTS[band]
    alloc["cash_instruments"] = CASH_INSTRUMENTS
    return alloc
