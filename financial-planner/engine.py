"""
Financial planning engine: scoring, recommendations, action plans, and PDF output.
India-specific assumptions live in india_profiles.py.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from india_profiles import (
    DATA_EFFECTIVE_FROM,
    DATA_SOURCES,
    INFLATION_INDIA,
    LAST_UPDATED,
    RETURN_ASSUMPTIONS,
    TAX_NOTES,
    get_allocation,
)


RISK_ORDER = {"conservative": 0, "moderate": 1, "aggressive": 2}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Goal:
    name: str
    target_amount: float
    years: int
    priority: str  # high / medium / low
    target_is_today_value: bool = True
    existing_allocated: float = 0.0


@dataclass
class Loan:
    name: str
    balance: float
    annual_rate: float
    monthly_emi: float


@dataclass
class UserProfile:
    age: int
    dependents: int
    monthly_income: float
    other_income: float
    monthly_expenses: float
    savings: float
    emergency_fund: float
    has_health_insurance: bool
    life_insurance_coverage: float
    existing_investments: float
    investment_type: str
    risk_profile: str
    goals: list[Goal]
    loans: list[Loan] = field(default_factory=list)
    tax_regime: str = "new"
    risk_capacity_score: int = 2
    risk_tolerance_score: int = 2
    auto_allocate_existing: bool = False
    inflation_rate: float = INFLATION_INDIA
    return_adjustment: float = 0.0
    retirement_age: int = 60
    life_expectancy: int = 85
    retirement_monthly_expenses: float = 0.0
    retirement_corpus: float = 0.0


def monthly_investment_needed(
    target: float,
    years: int,
    annual_return: float,
    existing: float = 0,
) -> float:
    """PMT calculation: how much to invest monthly to reach target."""
    n = years * 12
    if n <= 0:
        return max(0, target - existing)
    r = annual_return / 12
    fv_existing = existing * (1 + r) ** n
    remaining = max(0, target - fv_existing)
    if remaining == 0:
        return 0
    if r == 0:
        return remaining / n
    return remaining * r / ((1 + r) ** n - 1)


def future_value(today_value: float, years: int, inflation_rate: float = INFLATION_INDIA) -> float:
    return today_value * ((1 + inflation_rate) ** years)


def risk_profile_from_score(score: int) -> str:
    if score <= 1:
        return "conservative"
    if score == 2:
        return "moderate"
    return "aggressive"


def stricter_risk_profile(*profiles: str) -> str:
    clean = [p for p in profiles if p in RISK_ORDER]
    if not clean:
        return "moderate"
    return min(clean, key=lambda p: RISK_ORDER[p])


def adjusted_return(base_return: float, p: UserProfile) -> float:
    return max(0, base_return + p.return_adjustment)


def total_monthly_income(p: UserProfile) -> float:
    return p.monthly_income + p.other_income


def total_monthly_emi(p: UserProfile) -> float:
    return sum(l.monthly_emi for l in p.loans)


def monthly_surplus(p: UserProfile) -> float:
    return total_monthly_income(p) - p.monthly_expenses - total_monthly_emi(p)


def total_debt(p: UserProfile) -> float:
    return sum(l.balance for l in p.loans)


def high_interest_debt(p: UserProfile) -> float:
    return sum(l.balance for l in p.loans if l.annual_rate >= 0.12)


def high_interest_emi(p: UserProfile) -> float:
    return sum(l.monthly_emi for l in p.loans if l.annual_rate >= 0.12)


def goal_future_target(g: Goal, p: UserProfile) -> float:
    if g.target_is_today_value:
        return future_value(g.target_amount, g.years, p.inflation_rate)
    return g.target_amount


def sorted_goals(goals: list[Goal]) -> list[Goal]:
    return sorted(goals, key=lambda g: (PRIORITY_ORDER.get(g.priority, 1), g.years))


def allocation_split(monthly_needed: float, alloc: dict) -> dict:
    return {
        "equity": monthly_needed * alloc["equity"],
        "debt": monthly_needed * alloc["debt"],
        "gold": monthly_needed * alloc["gold"],
        "cash": monthly_needed * alloc["cash"],
    }


def scenario_values(monthly_needed: float, years: int, base_return: float) -> dict:
    scenarios = {
        "conservative": max(0, base_return - 0.02),
        "base": base_return,
        "optimistic": base_return + 0.02,
    }
    n = years * 12
    values = {}
    for label, annual_return in scenarios.items():
        r = annual_return / 12
        if r == 0:
            values[label] = monthly_needed * n
        else:
            values[label] = monthly_needed * (((1 + r) ** n - 1) / r)
    return values


def build_tradeoffs(rec: dict, p: UserProfile) -> dict:
    target = rec["future_target"]
    years = rec["years"]
    annual_return = rec["return"]
    existing = rec["existing_applied"]
    current = rec["monthly_needed"]

    extend_years = min(50, years + 2)
    extended = monthly_investment_needed(target, extend_years, annual_return, existing)
    reduced_target = target * 0.9
    reduced = monthly_investment_needed(reduced_target, years, annual_return, existing)
    surplus = max(0, monthly_surplus(p))

    return {
        "extend_by_2_years": extended,
        "reduce_target_10pct": reduced,
        "increase_needed": max(0, current - surplus),
        "available_surplus": surplus,
    }


def goal_recommendations(p: UserProfile) -> list[dict]:
    recs = []
    surplus_remaining = monthly_surplus(p)
    explicit_existing = sum(g.existing_allocated for g in p.goals)
    pool_existing = max(0, p.existing_investments - explicit_existing) if p.auto_allocate_existing else 0

    for g in sorted_goals(p.goals):
        alloc = get_allocation(g.years, p.risk_profile)
        annual_return = adjusted_return(alloc["return"], p)
        target = goal_future_target(g, p)
        pool_applied = min(pool_existing, target) if p.auto_allocate_existing else 0
        pool_existing = max(0, pool_existing - pool_applied)
        existing_applied = min(target, g.existing_allocated + pool_applied)
        monthly_needed = monthly_investment_needed(target, g.years, annual_return, existing_applied)
        feasible = monthly_needed <= surplus_remaining
        surplus_remaining = max(0, surplus_remaining - monthly_needed)
        split = allocation_split(monthly_needed, alloc)

        rec = {
            "name": g.name,
            "today_target": g.target_amount,
            "target": target,
            "future_target": target,
            "years": g.years,
            "priority": g.priority,
            "monthly_needed": monthly_needed,
            "allocation": alloc,
            "return": annual_return,
            "asset_sip_split": split,
            "existing_applied": existing_applied,
            "target_is_today_value": g.target_is_today_value,
            "feasible": feasible,
            "scenarios": scenario_values(monthly_needed, g.years, annual_return),
        }
        rec["tradeoffs"] = build_tradeoffs(rec, p)
        rec["fund_category_guidance"] = fund_category_guidance(rec, p)
        recs.append(rec)

    return recs


def total_monthly_needed(recs: list[dict]) -> float:
    return sum(r["monthly_needed"] for r in recs)


def fund_category_guidance(rec: dict, p: UserProfile) -> dict:
    years = rec["years"]
    alloc = rec["allocation"]
    suitable = []
    cautious = []
    avoid = []

    if years < 3:
        suitable.extend(["Liquid funds or overnight funds", "Bank FD or short-term deposit", "Ultra-short duration debt funds"])
        if p.tax_regime == "old":
            suitable.append("Tax-saving deposits only if lock-in matches the goal")
        cautious.append("Arbitrage funds if you understand short-term volatility and exit loads")
        avoid.extend(["Small-cap funds", "Sector or thematic funds", "Direct stocks", "Long-duration debt funds"])
    elif years < 7:
        suitable.extend(["Large-cap index funds", "Flexi-cap funds with a conservative debt mix", "Short-duration debt funds or PPF for the debt bucket"])
        if alloc["gold"] > 0:
            suitable.append("Gold ETF or gold fund for the gold bucket")
        cautious.extend(["Large & mid-cap funds", "Small-cap exposure above a small satellite allocation"])
        avoid.extend(["Single-stock bets for core goals", "Lock-ins that outlast the goal date"])
    else:
        suitable.extend(["Nifty 50 or broad-market index funds", "Flexi-cap funds", "Large & mid-cap funds", "PPF, EPF/VPF, or NPS for long-term debt allocation"])
        if years >= 10 and p.risk_profile != "conservative":
            cautious.append("Small-cap funds as a limited satellite allocation")
        if alloc["gold"] > 0:
            suitable.append("SGB if available at fair pricing, otherwise gold ETF or gold fund")
        avoid.extend(["Market timing with core SIPs", "Concentrated sector funds as the main portfolio"])

    return {"suitable": suitable, "use_caution": cautious, "avoid": avoid}


def tax_smart_notes(p: UserProfile, recs: list[dict]) -> list[str]:
    notes = [
        f"Equity mutual fund gains need holding-period awareness. {TAX_NOTES['equity_ltcg']}",
        f"Debt and FD choices should be compared after tax. {TAX_NOTES['debt_mf']}",
    ]
    if p.tax_regime == "new":
        notes.append("New-regime users should treat ELSS, PPF, and NPS primarily as investment or retirement choices, not automatic deduction tools.")
    else:
        notes.append("Old-regime users should review 80C, 80D, HRA, LTA, and NPS room before the financial year closes.")
    if any(r["years"] <= 3 for r in recs):
        notes.append("Near-term goals should prioritise certainty and liquidity over tax optimisation.")
    if any(r["allocation"]["gold"] > 0 for r in recs):
        notes.append("Gold exposure should be sized as diversification; check liquidity, spreads, and tax treatment before choosing ETF, fund, or SGB.")
    notes.append("At year-end, review tax harvesting only after brokerage, exit load, and your full capital-gains picture are clear.")
    return notes


def debt_strategy(p: UserProfile) -> dict:
    income = total_monthly_income(p)
    emis = total_monthly_emi(p)
    emi_ratio = emis / income if income > 0 else 0
    high_debt = high_interest_debt(p)
    items = []

    if not p.loans:
        summary = "No active loans entered. Keep future EMIs below a comfortable share of income before adding new goals."
        items.append("Avoid taking new debt for discretionary goals until the emergency fund is at least 3 months.")
    elif high_debt > 0:
        summary = "High-interest debt is the first money leak to close."
        items.append(f"Prioritise repayment of about Rs.{high_debt:,.0f} before scaling low-priority equity SIPs.")
        items.append("Use an avalanche order: highest interest rate first, while keeping minimum EMIs current on every loan.")
    elif emi_ratio > 0.35:
        summary = "EMIs are taking a large share of income, so flexibility is tight."
        items.append("Pause new low-priority goals and reduce EMI pressure before increasing market risk.")
    else:
        summary = "Debt load looks manageable from the inputs provided."
        items.append("Continue EMIs on schedule and compare any prepayment with goal SIP shortfalls.")

    if p.loans:
        items.append(f"Current EMI load is {emi_ratio:.0%} of monthly income.")
    if any(l.annual_rate < 0.10 for l in p.loans):
        items.append("For lower-rate home or education loans, compare prepayment with investing only after insurance and emergency fund are in place.")
    return {"summary": summary, "items": items}


def avoid_list(p: UserProfile, recs: list[dict], gaps: list[str]) -> list[str]:
    avoids = []
    fixed_outflow = p.monthly_expenses + total_monthly_emi(p)
    if fixed_outflow > 0 and p.emergency_fund < fixed_outflow * 3:
        avoids.append("Avoid aggressive investing before building at least a 3-month emergency fund.")
    if high_interest_debt(p) > 0:
        avoids.append("Avoid increasing discretionary SIPs while credit-card or personal-loan style debt is outstanding.")
    if not p.has_health_insurance:
        avoids.append("Avoid relying on investments as your medical safety net; health insurance comes first.")
    if p.dependents > 0 and p.life_insurance_coverage < total_monthly_income(p) * 120:
        avoids.append("Avoid investment-linked insurance as a substitute for adequate pure term cover.")
    if any(r["years"] < 3 and r["allocation"]["equity"] > 0 for r in recs):
        avoids.append("Avoid high equity exposure for goals due within 3 years.")
    if total_monthly_needed(recs) > max(0, monthly_surplus(p)):
        avoids.append("Avoid funding every goal at once; sequence high-priority goals first.")
    if not avoids and not gaps:
        avoids.append("Avoid changing a working plan too often; review annually or after major life changes.")
    return avoids


def personality_summary(p: UserProfile, health: dict, recs: list[dict]) -> dict:
    surplus = monthly_surplus(p)
    needed = total_monthly_needed(recs)
    fixed_outflow = p.monthly_expenses + total_monthly_emi(p)
    months = p.emergency_fund / fixed_outflow if fixed_outflow > 0 else 0

    if health["total"] < 45 or surplus <= 0:
        label = "Stabiliser"
        summary = "Your plan needs cash-flow stability before ambition."
        next_rupee = "Your next rupee should reduce fixed pressure or build emergency cash."
    elif high_interest_debt(p) > 0:
        label = "Debt Breaker"
        summary = "Your biggest upside comes from closing expensive debt leaks."
        next_rupee = "Your next rupee should attack the highest-interest loan."
    elif months < 3:
        label = "Foundation Builder"
        summary = "Your investing plan gets stronger once the safety buffer is real."
        next_rupee = "Your next rupee should build the emergency fund."
    elif needed > surplus:
        label = "Goal Stretcher"
        summary = "Your goals are meaningful, but the plan needs sequencing."
        next_rupee = "Your next rupee should go to the highest-priority goal."
    elif health["total"] >= 70 and surplus > needed:
        label = "Wealth Accelerator"
        summary = "You have room to fund goals and still keep flexibility."
        next_rupee = "Your next rupee can increase long-term goal SIPs or retirement funding."
    else:
        label = "Steady Builder"
        summary = "You are building well; consistency matters more than complexity."
        next_rupee = "Your next rupee should keep the automated goal SIPs moving."

    return {"label": label, "summary": summary, "next_rupee": next_rupee}


def personal_finance_playbook(
    p: UserProfile,
    health: dict,
    recs: list[dict],
    gaps: list[str],
) -> dict:
    personality = personality_summary(p, health, recs)
    debt = debt_strategy(p)
    tax_notes = tax_smart_notes(p, recs)
    avoids = avoid_list(p, recs, gaps)
    needed = total_monthly_needed(recs)
    surplus = monthly_surplus(p)

    answers = []
    if needed <= max(0, surplus):
        answers.append("Are my SIPs enough? Yes, based on current assumptions and entered goals.")
    else:
        answers.append(f"Are my SIPs enough? Not yet; the current plan is short by about Rs.{needed - max(0, surplus):,.0f}/month.")
    if high_interest_debt(p) > 0:
        answers.append("Should I invest before debt repayment? Keep only essential SIPs; expensive debt gets priority.")
    elif p.emergency_fund < (p.monthly_expenses + total_monthly_emi(p)) * 3:
        answers.append("Should I invest before emergency cash? Build the buffer first, then scale SIPs.")
    else:
        answers.append("Should I stop SIPs in a market fall? For long-term goals, continue unless cash flow breaks.")
    answers.append(f"Which tax lens matters? {tax_notes[0]}")

    return {
        "personality": personality,
        "one_sentence": personality["next_rupee"],
        "answers": answers,
        "tax_notes": tax_notes,
        "debt_strategy": debt,
        "avoid": avoids,
    }


def compute_health_score(p: UserProfile) -> dict:
    scores = {}
    details = {}
    income = total_monthly_income(p)
    surplus = monthly_surplus(p)
    emis = total_monthly_emi(p)

    months_covered = p.emergency_fund / (p.monthly_expenses + emis) if (p.monthly_expenses + emis) > 0 else 0
    if months_covered >= 6:
        scores["emergency_fund"] = 20
        details["emergency_fund"] = f"{months_covered:.1f} months covered. Strong safety buffer."
    elif months_covered >= 3:
        scores["emergency_fund"] = 13
        details["emergency_fund"] = f"{months_covered:.1f} months covered. Good; aim for 6."
    elif months_covered >= 1:
        scores["emergency_fund"] = 6
        details["emergency_fund"] = f"{months_covered:.1f} month(s) covered. Build this to 3-6 months."
    else:
        scores["emergency_fund"] = 0
        details["emergency_fund"] = "No emergency fund. This is your first priority."

    savings_rate = surplus / income if income > 0 else 0
    if savings_rate >= 0.20:
        scores["savings_rate"] = 20
        details["savings_rate"] = f"{savings_rate:.0%} savings rate after EMIs. Excellent discipline."
    elif savings_rate >= 0.15:
        scores["savings_rate"] = 15
        details["savings_rate"] = f"{savings_rate:.0%} savings rate after EMIs. Good; push toward 20%."
    elif savings_rate >= 0.10:
        scores["savings_rate"] = 10
        details["savings_rate"] = f"{savings_rate:.0%} savings rate after EMIs. Acceptable, with room to improve."
    elif savings_rate >= 0.05:
        scores["savings_rate"] = 5
        details["savings_rate"] = f"{savings_rate:.0%} savings rate after EMIs. Low; review expenses."
    else:
        scores["savings_rate"] = 0
        details["savings_rate"] = f"{savings_rate:.0%} savings rate after EMIs. Cash flow needs attention."

    if p.has_health_insurance:
        scores["health_insurance"] = 15
        details["health_insurance"] = "Health insurance is in place."
    else:
        scores["health_insurance"] = 0
        details["health_insurance"] = "No health insurance. A medical emergency can derail the plan."

    recommended_coverage = income * 120
    if p.dependents == 0:
        scores["life_insurance"] = 15
        details["life_insurance"] = "No dependents. Life insurance is not critical right now."
    elif p.savings + p.existing_investments >= recommended_coverage:
        scores["life_insurance"] = 15
        details["life_insurance"] = "Savings and investments exceed the 10x annual income protection benchmark."
    elif p.life_insurance_coverage >= recommended_coverage:
        scores["life_insurance"] = 15
        details["life_insurance"] = "Life cover meets the 10x annual income benchmark."
    elif p.life_insurance_coverage >= recommended_coverage * 0.5:
        shortfall = recommended_coverage - p.life_insurance_coverage
        scores["life_insurance"] = 8
        details["life_insurance"] = f"Life cover is partial. Increase by Rs.{shortfall:,.0f}."
    else:
        scores["life_insurance"] = 0
        details["life_insurance"] = f"{p.dependents} dependent(s) need stronger protection. Recommended cover: Rs.{recommended_coverage:,.0f}."

    recs = goal_recommendations(p)
    needed = total_monthly_needed(recs)
    blocked_by_debt = high_interest_debt(p) > 0
    if needed == 0:
        scores["goal_feasibility"] = 30
        details["goal_feasibility"] = "All goals are currently funded."
    elif blocked_by_debt:
        scores["goal_feasibility"] = 10 if needed <= max(0, surplus) else 0
        details["goal_feasibility"] = "High-interest debt should be handled before full goal investing."
    elif needed <= surplus * 0.8:
        scores["goal_feasibility"] = 30
        details["goal_feasibility"] = "Current surplus comfortably covers all goal SIPs."
    elif needed <= surplus:
        scores["goal_feasibility"] = 20
        details["goal_feasibility"] = "Goals are achievable but leave little buffer."
    elif needed <= surplus * 1.25:
        scores["goal_feasibility"] = 10
        details["goal_feasibility"] = "Goals slightly exceed current capacity. Adjust timelines or targets."
    else:
        scores["goal_feasibility"] = 0
        details["goal_feasibility"] = "Goals significantly exceed current capacity."

    total = sum(scores.values())
    return {"total": total, "scores": scores, "details": details}


def gap_analysis(p: UserProfile) -> list[str]:
    gaps = []
    income = total_monthly_income(p)
    surplus = monthly_surplus(p)
    fixed_outflow = p.monthly_expenses + total_monthly_emi(p)
    recommended_coverage = income * 120

    if p.emergency_fund < fixed_outflow * 3:
        months = p.emergency_fund / fixed_outflow if fixed_outflow > 0 else 0
        needed = fixed_outflow * 3 - p.emergency_fund
        gaps.append(
            f"Emergency fund covers {months:.1f} months. Build at least 3 months by adding Rs.{needed:,.0f} "
            "to a liquid fund, overnight fund, or savings account."
        )

    if not p.has_health_insurance:
        gaps.append(
            "Buy health insurance before increasing risky investments. Start with at least Rs.10L individual "
            "or Rs.20L family floater cover, then review based on city and family needs."
        )

    if p.dependents > 0 and p.life_insurance_coverage < recommended_coverage and p.savings + p.existing_investments < recommended_coverage:
        shortfall = recommended_coverage - max(p.life_insurance_coverage, 0)
        gaps.append(
            f"Increase term life cover by about Rs.{shortfall:,.0f}. Prefer a pure term plan and avoid mixing "
            "insurance with investments."
        )

    if high_interest_debt(p) > 0:
        gaps.append(
            f"High-interest debt outstanding: Rs.{high_interest_debt(p):,.0f}. Route spare cash toward repayment "
            "before starting or scaling discretionary equity SIPs."
        )

    if surplus <= 0:
        gaps.append("Expenses plus EMIs meet or exceed income. Reduce fixed outflows before funding new goals.")
    else:
        savings_rate = surplus / income if income > 0 else 0
        if savings_rate < 0.10:
            gaps.append(f"Savings rate after EMIs is {savings_rate:.0%}. Target 15-20% before adding low-priority goals.")

    if p.tax_regime == "new":
        gaps.append(
            "You selected the new tax regime. Treat ELSS, PPF, and NPS as investment choices first; do not assume "
            "80C or 80CCD deductions unless your tax setup allows them."
        )

    return gaps


def action_plan(p: UserProfile, recs: list[dict], gaps: list[str]) -> list[dict]:
    surplus = max(0, monthly_surplus(p))
    fixed_outflow = p.monthly_expenses + total_monthly_emi(p)
    ef_gap = max(0, fixed_outflow * 3 - p.emergency_fund)
    top_goal = recs[0] if recs else None

    plan = []
    first_steps = []
    if ef_gap > 0:
        first_steps.append(f"Move Rs.{min(surplus, ef_gap):,.0f}/month toward the emergency fund.")
    if not p.has_health_insurance:
        first_steps.append("Shortlist and buy health insurance before adding new risky investments.")
    if high_interest_debt(p) > 0:
        first_steps.append("Freeze new low-priority SIPs and attack high-interest debt.")
    if not first_steps:
        first_steps.append("Start the high-priority goal SIPs immediately.")
    plan.append({"period": "Next 30 days", "items": first_steps})

    second_steps = []
    if p.dependents > 0 and p.life_insurance_coverage < total_monthly_income(p) * 120:
        second_steps.append("Close the term-insurance shortfall.")
    if top_goal:
        second_steps.append(f"Set up the first automated SIP for {top_goal['name']}: Rs.{top_goal['monthly_needed']:,.0f}/month.")
    if p.tax_regime == "old":
        second_steps.append("Review PPF/ELSS/NPS usage against remaining 80C and 80CCD room.")
    else:
        second_steps.append("Use tax-saving products only if they still fit the goal, lock-in, and liquidity needs.")
    plan.append({"period": "Next 60 days", "items": second_steps})

    third_steps = []
    if recs:
        total_needed = sum(r["monthly_needed"] for r in recs)
        third_steps.append(f"Review whether total goal SIPs of Rs.{total_needed:,.0f}/month fit comfortably.")
        third_steps.append("Rebalance goal allocations once a year or when income changes materially.")
    third_steps.append("Update this plan after any job, EMI, family, or tax-regime change.")
    plan.append({"period": "Next 90 days", "items": third_steps})
    return plan


def job_loss_buffer_months(p: UserProfile) -> float:
    fixed_outflow = p.monthly_expenses + total_monthly_emi(p)
    return (p.savings + p.emergency_fund) / fixed_outflow if fixed_outflow > 0 else 0


def retirement_summary(p: UserProfile) -> dict:
    years_to_retirement = max(0, p.retirement_age - p.age)
    retirement_years = max(0, p.life_expectancy - p.retirement_age)
    monthly_need_today = p.retirement_monthly_expenses or p.monthly_expenses
    monthly_need_at_retirement = future_value(monthly_need_today, years_to_retirement, p.inflation_rate)
    corpus_needed = monthly_need_at_retirement * 12 * retirement_years
    annual_return = adjusted_return(get_allocation(max(1, years_to_retirement), p.risk_profile)["return"], p)
    monthly_needed = monthly_investment_needed(corpus_needed, max(1, years_to_retirement), annual_return, p.retirement_corpus)
    return {
        "years_to_retirement": years_to_retirement,
        "retirement_years": retirement_years,
        "monthly_need_at_retirement": monthly_need_at_retirement,
        "corpus_needed": corpus_needed,
        "monthly_needed": monthly_needed,
    }


DARK = colors.HexColor("#1a1a1a")
MID = colors.HexColor("#444444")
LIGHT = colors.HexColor("#888888")
RULE = colors.HexColor("#dddddd")
GREEN = colors.HexColor("#2d7d46")
AMBER = colors.HexColor("#b45309")
RED = colors.HexColor("#b91c1c")
ALT_ROW = colors.HexColor("#f9fafb")
HDR_BG = colors.HexColor("#e5e7eb")
SCORE_BG_GOOD = colors.HexColor("#dcfce7")
SCORE_BG_WARN = colors.HexColor("#fef9c3")
SCORE_BG_BAD = colors.HexColor("#fee2e2")


def score_color(score: int) -> colors.HexColor:
    if score >= 70:
        return GREEN
    if score >= 45:
        return AMBER
    return RED


def score_label(score: int) -> str:
    if score >= 70:
        return "Healthy"
    if score >= 45:
        return "Needs Attention"
    return "At Risk"


def _score_bg(score: int, max_score: int) -> colors.Color:
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.70:
        return SCORE_BG_GOOD
    if pct >= 0.40:
        return SCORE_BG_WARN
    return SCORE_BG_BAD


def _score_fg(score: int, max_score: int) -> colors.Color:
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.70:
        return GREEN
    if pct >= 0.40:
        return AMBER
    return RED


def _make_goal_summary_table(recs: list[dict]) -> Table:
    """One-row-per-goal overview table: name, priority, horizon, targets, SIP, feasibility, split."""
    headers = ["Goal", "Priority", "Yrs", "Future Target", "Monthly SIP", "Feasible", "Split"]
    col_w = [44 * mm, 18 * mm, 12 * mm, 28 * mm, 26 * mm, 20 * mm, 26 * mm]
    rows = [headers]
    for rec in recs:
        alloc = rec["allocation"]
        parts = [f"{alloc['equity'] * 100:.0f}E", f"{alloc['debt'] * 100:.0f}D"]
        if alloc["gold"] > 0:
            parts.append(f"{alloc['gold'] * 100:.0f}G")
        if alloc["cash"] > 0:
            parts.append(f"{alloc['cash'] * 100:.0f}C")
        rows.append([
            rec["name"][:28],
            rec["priority"].capitalize(),
            str(rec["years"]),
            f"Rs.{rec['future_target']:,.0f}",
            f"Rs.{rec['monthly_needed']:,.0f}",
            "Yes" if rec["feasible"] else "Stretch",
            " ".join(parts),
        ])
    t = Table(rows, colWidths=col_w)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), HDR_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
    ]
    for i, rec in enumerate(recs, start=1):
        fg = GREEN if rec["feasible"] else AMBER
        style.extend([
            ("TEXTCOLOR", (5, i), (5, i), fg),
            ("FONTNAME", (5, i), (5, i), "Helvetica-Bold"),
        ])
    t.setStyle(TableStyle(style))
    return t


def _make_checklist_table(actions: list[dict]) -> Table:
    """Printable action checklist with Done / Action / Complete By columns."""
    today = date.today()
    period_dates = {
        "Next 30 days": (today + timedelta(days=30)).strftime("%b %d, %Y"),
        "Next 60 days": (today + timedelta(days=60)).strftime("%b %d, %Y"),
        "Next 90 days": (today + timedelta(days=90)).strftime("%b %d, %Y"),
    }
    col_w = [14 * mm, 126 * mm, 34 * mm]
    rows = [["Done", "Recommended Action", "Complete By"]]
    for block in actions:
        complete_by = period_dates.get(block["period"], "")
        for item in block["items"]:
            rows.append(["□", item, complete_by])
    t = Table(rows, colWidths=col_w)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTSIZE", (0, 1), (0, -1), 11),
        ("BACKGROUND", (0, 0), (-1, 0), HDR_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (1, 1), (1, -1), MID),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
    ]))
    return t


def _make_debt_table(p: "UserProfile") -> Optional[Table]:
    """Per-loan table with priority and recommended action. None if no loans."""
    if not p.loans:
        return None
    col_w = [36 * mm, 28 * mm, 16 * mm, 26 * mm, 20 * mm, 48 * mm]
    rows = [["Loan", "Outstanding", "Rate", "Monthly EMI", "Priority", "Recommended Action"]]
    for loan in p.loans:
        is_high = loan.annual_rate >= 0.12
        rows.append([
            loan.name[:22],
            f"Rs.{loan.balance:,.0f}",
            f"{loan.annual_rate * 100:.1f}%",
            f"Rs.{loan.monthly_emi:,.0f}",
            "High" if is_high else "Normal",
            "Repay before scaling new SIPs" if is_high else "Continue schedule; compare prepayment vs SIP return",
        ])
    t = Table(rows, colWidths=col_w)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), HDR_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
        ("ALIGN", (1, 0), (4, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (5, 0), (5, -1), "LEFT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
    ]
    for i, loan in enumerate(p.loans, start=1):
        if loan.annual_rate >= 0.12:
            style.extend([
                ("TEXTCOLOR", (4, i), (4, i), RED),
                ("FONTNAME", (4, i), (4, i), "Helvetica-Bold"),
            ])
    t.setStyle(TableStyle(style))
    return t


def S(name, **kw):
    base = dict(
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=DARK,
        spaceAfter=0,
        spaceBefore=0,
        alignment=TA_LEFT,
    )
    base.update(kw)
    return ParagraphStyle(name, **base)


def rule():
    return HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=4, spaceBefore=2)


def section(title):
    return [
        Paragraph(title.upper(), S("sec", fontName="Helvetica-Bold", fontSize=8.5, letterSpacing=1.2, spaceBefore=10, spaceAfter=2)),
        rule(),
    ]


def sp(h=4):
    return Spacer(1, h)


def b(text):
    return Paragraph(f"- {text}", S("bul", fontSize=9.5, leading=13.5, leftIndent=0, spaceAfter=2, alignment=TA_JUSTIFY))


def generate_pdf(
    p: UserProfile,
    health: dict,
    recs: list[dict],
    gaps: list[str],
    output_path: str,
    actions: Optional[list[dict]] = None,
    playbook: Optional[dict] = None,
):
    actions = actions or action_plan(p, recs, gaps)
    playbook = playbook or personal_finance_playbook(p, health, recs, gaps)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title="Personal Financial Plan",
        author="Financial Planner",
    )

    def rs(n):
        return f"Rs. {n:,.0f}"

    story = []

    # ── Title ──────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "Personal Financial Plan",
        S("title", fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_CENTER),
    ))
    story.append(Paragraph(
        f"Age {p.age}  |  {p.dependents} dependent(s)  |  {p.risk_profile.capitalize()} risk  |  {p.tax_regime.capitalize()} tax regime",
        S("sub", fontSize=9, textColor=MID, alignment=TA_CENTER, spaceAfter=2),
    ))
    story.append(Paragraph(
        f"Generated: {date.today().strftime('%B %d, %Y')}",
        S("gen", fontSize=8, textColor=LIGHT, alignment=TA_CENTER, spaceAfter=4),
    ))
    story.append(sp(8))

    # ── Financial Snapshot ─────────────────────────────────────────────────
    surplus = monthly_surplus(p)
    story += section("Financial Snapshot")
    snap_rows = [
        ["Monthly income", rs(total_monthly_income(p))],
        ["Monthly expenses", rs(p.monthly_expenses)],
        ["Monthly EMIs", rs(total_monthly_emi(p))],
        ["Surplus after EMIs", rs(surplus)],
        ["Total goal SIP needed / month", rs(total_monthly_needed(recs))],
        ["Surplus after goals", rs(max(0, surplus - total_monthly_needed(recs)))],
        ["Savings + emergency fund", rs(p.savings + p.emergency_fund)],
        ["Existing investments", rs(p.existing_investments)],
        ["Debt outstanding", rs(total_debt(p))],
        ["Job-loss buffer", f"{job_loss_buffer_months(p):.1f} months"],
    ]
    snap = Table(snap_rows, colWidths=[100 * mm, 74 * mm])
    snap.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), MID),
        ("TEXTCOLOR", (1, 0), (1, -1), DARK),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ALT_ROW]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(snap)
    story.append(sp(6))

    # ── Health Score ───────────────────────────────────────────────────────
    total = health["total"]
    col = score_color(total)
    story += section("Financial Health Score")
    story.append(Paragraph(
        f'<font color="{col.hexval()}" size="28"><b>{total}</b></font>'
        f'<font size="12" color="{col.hexval()}">  /  100  —  {score_label(total)}</font>',
        S("score", leading=36, spaceBefore=4, spaceAfter=6),
    ))
    SCORE_MAXES = [
        ("emergency_fund", "Emergency Fund", 20),
        ("savings_rate", "Savings Rate", 20),
        ("health_insurance", "Health Insurance", 15),
        ("life_insurance", "Life Insurance", 15),
        ("goal_feasibility", "Goal Feasibility", 30),
    ]
    score_rows = [["Category", "Score", "Max", "Detail"]]
    for k, label, max_v in SCORE_MAXES:
        score_rows.append([label, str(health["scores"][k]), str(max_v), health["details"][k]])
    score_tbl = Table(score_rows, colWidths=[42 * mm, 16 * mm, 14 * mm, 102 * mm])
    score_style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), HDR_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 1), (0, -1), MID),
        ("TEXTCOLOR", (3, 1), (3, -1), MID),
        ("ALIGN", (1, 0), (2, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
    ]
    for i, (k, _, max_v) in enumerate(SCORE_MAXES, start=1):
        s = health["scores"][k]
        score_style.extend([
            ("BACKGROUND", (1, i), (2, i), _score_bg(s, max_v)),
            ("TEXTCOLOR", (1, i), (2, i), _score_fg(s, max_v)),
            ("FONTNAME", (1, i), (1, i), "Helvetica-Bold"),
        ])
    score_tbl.setStyle(TableStyle(score_style))
    story.append(score_tbl)
    story.append(sp(6))

    # ── Goal Summary ───────────────────────────────────────────────────────
    if recs:
        story += section("Goal Summary")
        story.append(_make_goal_summary_table(recs))
        story.append(sp(6))

    # ── Action Checklist ───────────────────────────────────────────────────
    story += section("Action Checklist")
    story.append(_make_checklist_table(actions))
    story.append(sp(6))

    # ── Key Warnings ───────────────────────────────────────────────────────
    if gaps:
        story += section("Key Warnings")
        for g in gaps:
            story.append(b(g))
        story.append(sp(4))

    # ── Debt Strategy ──────────────────────────────────────────────────────
    if p.loans:
        story += section("Debt Strategy")
        story.append(b(playbook["debt_strategy"]["summary"]))
        for item in playbook["debt_strategy"]["items"][:2]:
            story.append(b(item))
        debt_tbl = _make_debt_table(p)
        if debt_tbl:
            story.append(sp(4))
            story.append(debt_tbl)
        story.append(sp(4))

    # ── Personal Finance Playbook ──────────────────────────────────────────
    story += section("Personal Finance Playbook")
    personality = playbook["personality"]
    story.append(b(f"{personality['label']}: {personality['summary']} {playbook['one_sentence']}"))
    for answer in playbook["answers"]:
        story.append(b(answer))
    story.append(Paragraph("Tax-smart notes", S("ap", fontName="Helvetica-Bold", fontSize=9.5, spaceBefore=5)))
    for note in playbook["tax_notes"][:3]:
        story.append(b(note))
    story.append(Paragraph("Avoid for now", S("ap", fontName="Helvetica-Bold", fontSize=9.5, spaceBefore=5)))
    for item in playbook["avoid"][:4]:
        story.append(b(item))
    story.append(sp(4))

    # ── Goal Recommendations (detail) — starts on a fresh page ────────────
    story.append(PageBreak())
    story += section("Goal Recommendations")
    for rec in recs:
        alloc = rec["allocation"]
        split = rec["asset_sip_split"]
        feasibility = "Feasible" if rec["feasible"] else "Stretch — adjust target, SIP, or timeline"
        col_hex = GREEN.hexval() if rec["feasible"] else AMBER.hexval()
        items = [
            Paragraph(
                f'<b>{rec["name"]}</b>  |  {rec["priority"].capitalize()} priority  |  {rec["years"]} year{"s" if rec["years"] != 1 else ""}',
                S("gh", fontName="Helvetica-Bold", fontSize=10, spaceBefore=8, spaceAfter=2),
            ),
            Paragraph(
                f'Today: <b>{rs(rec["today_target"])}</b>  →  Future: <b>{rs(rec["future_target"])}</b>  |  '
                f'Monthly SIP: <b>{rs(rec["monthly_needed"])}</b>  |  <font color="{col_hex}">{feasibility}</font>',
                S("gm", fontSize=9, textColor=MID, spaceAfter=4),
            ),
            b(f"Existing investments applied: {rs(rec['existing_applied'])}."),
            b(f"Strategy: {alloc['label']} — expected return ~{rec['return'] * 100:.1f}% p.a."),
            b(
                f"Monthly split: {rs(split['equity'])} equity  /  {rs(split['debt'])} debt  /  "
                f"{rs(split['gold'])} gold  /  {rs(split['cash'])} cash/liquid."
            ),
        ]
        guidance = rec.get("fund_category_guidance", {})
        if guidance:
            suitable = "; ".join(guidance.get("suitable", [])[:3])
            avoid_items = "; ".join(guidance.get("avoid", [])[:2])
            items.extend([
                b(f"Suitable: {suitable}."),
                b(f"Avoid: {avoid_items}."),
            ])
        scen = rec["scenarios"]
        items.append(b(
            f"Scenarios: conservative {rs(scen['conservative'])}  /  base {rs(scen['base'])}  /  optimistic {rs(scen['optimistic'])}."
        ))
        if not rec["feasible"]:
            trade = rec["tradeoffs"]
            items.append(b(
                f"Trade-offs: extend 2 yrs → {rs(trade['extend_by_2_years'])}/mo;  "
                f"reduce target 10% → {rs(trade['reduce_target_10pct'])}/mo."
            ))
        story.append(KeepTogether(items))

    # ── Retirement Check ───────────────────────────────────────────────────
    story += section("Retirement Check")
    ret = retirement_summary(p)
    story.append(b(f"Years to retirement: {ret['years_to_retirement']}."))
    story.append(b(f"Estimated corpus needed: {rs(ret['corpus_needed'])}."))
    story.append(b(f"Monthly retirement SIP needed: {rs(ret['monthly_needed'])}."))
    story.append(b(f"Estimated monthly expenses at retirement: {rs(ret['monthly_need_at_retirement'])}."))

    # ── Assumptions & Guardrails ───────────────────────────────────────────
    story += section("Assumptions and Guardrails")
    story.append(b(f"Assumptions last reviewed: {LAST_UPDATED}; effective from {DATA_EFFECTIVE_FROM}."))
    story.append(b(f"Inflation: {p.inflation_rate * 100:.1f}% p.a.; return adjustment: {p.return_adjustment * 100:+.1f}% p.a."))
    story.append(b(f"Tax notes: {TAX_NOTES['equity_ltcg']} {TAX_NOTES['debt_mf']}"))
    story.append(b(
        "This app does not know your full tax status, liabilities, employer benefits, health conditions, "
        "existing asset allocation, or legal obligations."
    ))
    story.append(b("Consult a SEBI-registered investment adviser before making investment decisions."))
    for source in DATA_SOURCES:
        story.append(b(source))

    doc.build(story)
