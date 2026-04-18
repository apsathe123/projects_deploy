"""
Financial planning engine — scoring, recommendations, and PDF generation.
India-specific: uses india_profiles.py for asset allocations and instrument recommendations.
"""

from dataclasses import dataclass
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether, Table, TableStyle
)
from india_profiles import get_allocation


# ── Monthly investment needed ─────────────────────────────────────────────────
def monthly_investment_needed(target: float, years: int, annual_return: float,
                               existing: float = 0) -> float:
    """PMT calculation: how much to invest monthly to reach target."""
    n = years * 12
    r = annual_return / 12
    fv_existing = existing * (1 + r) ** n
    remaining = max(0, target - fv_existing)
    if remaining == 0:
        return 0
    if r == 0:
        return remaining / n
    return remaining * r / ((1 + r) ** n - 1)


# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class Goal:
    name: str
    target_amount: float
    years: int
    priority: str  # high / medium / low


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
    life_insurance_coverage: float  # 0 if none; recommended = 120x monthly income
    existing_investments: float
    investment_type: str            # e.g. stocks, property, pension, mixed
    risk_profile: str               # conservative / moderate / aggressive
    goals: list[Goal]


# ── Health score ──────────────────────────────────────────────────────────────
def compute_health_score(p: UserProfile) -> dict:
    scores = {}
    details = {}

    total_monthly_income = p.monthly_income + p.other_income
    monthly_surplus = total_monthly_income - p.monthly_expenses

    # 1. Emergency fund (0-20)
    months_covered = p.emergency_fund / p.monthly_expenses if p.monthly_expenses > 0 else 0
    if months_covered >= 6:
        scores["emergency_fund"] = 20
        details["emergency_fund"] = f"{months_covered:.1f} months covered — excellent."
    elif months_covered >= 3:
        scores["emergency_fund"] = 13
        details["emergency_fund"] = f"{months_covered:.1f} months covered — good, aim for 6."
    elif months_covered >= 1:
        scores["emergency_fund"] = 6
        details["emergency_fund"] = f"{months_covered:.1f} month(s) covered — build this up to 3-6 months."
    else:
        scores["emergency_fund"] = 0
        details["emergency_fund"] = "No emergency fund — this is your first priority."

    # 2. Savings rate (0-20)
    savings_rate = monthly_surplus / total_monthly_income if total_monthly_income > 0 else 0
    if savings_rate >= 0.20:
        scores["savings_rate"] = 20
        details["savings_rate"] = f"{savings_rate:.0%} savings rate — excellent discipline."
    elif savings_rate >= 0.15:
        scores["savings_rate"] = 15
        details["savings_rate"] = f"{savings_rate:.0%} savings rate — good, push toward 20%."
    elif savings_rate >= 0.10:
        scores["savings_rate"] = 10
        details["savings_rate"] = f"{savings_rate:.0%} savings rate — acceptable, room to improve."
    elif savings_rate >= 0.05:
        scores["savings_rate"] = 5
        details["savings_rate"] = f"{savings_rate:.0%} savings rate — low, review expenses."
    else:
        scores["savings_rate"] = 0
        details["savings_rate"] = f"{savings_rate:.0%} savings rate — critical. Expenses exceed or nearly match income."

    # 3. Health insurance (0-15)
    if p.has_health_insurance:
        scores["health_insurance"] = 15
        details["health_insurance"] = "Health insurance in place — good."
    else:
        scores["health_insurance"] = 0
        details["health_insurance"] = "No health insurance — a medical emergency could derail your entire plan."

    # 4. Life insurance (0-15)
    # Recommended = 10x annual income = 120x monthly take-home
    recommended_coverage = total_monthly_income * 120
    if p.dependents == 0:
        scores["life_insurance"] = 15
        details["life_insurance"] = "No dependents — life insurance not critical at this stage."
    elif p.savings >= recommended_coverage:
        scores["life_insurance"] = 15
        details["life_insurance"] = (
            f"Savings of Rs.{p.savings:,.0f} exceed the recommended coverage of "
            f"Rs.{recommended_coverage:,.0f} — dependents are financially protected."
        )
    elif p.life_insurance_coverage >= recommended_coverage:
        scores["life_insurance"] = 15
        details["life_insurance"] = (
            f"Life insurance coverage of Rs.{p.life_insurance_coverage:,.0f} meets "
            f"the recommended 10x annual income (Rs.{recommended_coverage:,.0f})."
        )
    elif p.life_insurance_coverage >= recommended_coverage * 0.5:
        shortfall = recommended_coverage - p.life_insurance_coverage
        scores["life_insurance"] = 8
        details["life_insurance"] = (
            f"Coverage of Rs.{p.life_insurance_coverage:,.0f} is below the recommended "
            f"Rs.{recommended_coverage:,.0f}. Increase by Rs.{shortfall:,.0f}."
        )
    else:
        scores["life_insurance"] = 0
        details["life_insurance"] = (
            f"{p.dependents} dependent(s) with no adequate life insurance or savings. "
            f"Recommended coverage: Rs.{recommended_coverage:,.0f} (10x annual income)."
        )

    # 5. Goal feasibility (0-30)
    total_monthly_needed = sum(
        monthly_investment_needed(
            g.target_amount, g.years,
            get_allocation(g.years, p.risk_profile)["return"]
        )
        for g in p.goals
    )
    if total_monthly_needed == 0:
        scores["goal_feasibility"] = 30
        details["goal_feasibility"] = "No goals defined or all goals already funded."
    elif total_monthly_needed <= monthly_surplus * 0.8:
        scores["goal_feasibility"] = 30
        details["goal_feasibility"] = "Current surplus comfortably covers all goals."
    elif total_monthly_needed <= monthly_surplus:
        scores["goal_feasibility"] = 20
        details["goal_feasibility"] = "Goals are achievable but leave little buffer — consider prioritising."
    elif total_monthly_needed <= monthly_surplus * 1.25:
        scores["goal_feasibility"] = 10
        details["goal_feasibility"] = "Goals slightly exceed current capacity — extend timelines or reduce targets."
    else:
        scores["goal_feasibility"] = 0
        details["goal_feasibility"] = "Goals significantly exceed current capacity — restructuring needed."

    total = sum(scores.values())
    return {"total": total, "scores": scores, "details": details}


# ── Per-goal recommendations ──────────────────────────────────────────────────
def goal_recommendations(p: UserProfile) -> list[dict]:
    recs = []
    monthly_surplus = (p.monthly_income + p.other_income) - p.monthly_expenses

    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_goals = sorted(p.goals, key=lambda g: (priority_order.get(g.priority, 1), g.years))

    surplus_remaining = monthly_surplus

    for g in sorted_goals:
        alloc = get_allocation(g.years, p.risk_profile)
        monthly_needed = monthly_investment_needed(g.target_amount, g.years, alloc["return"])
        feasible = monthly_needed <= surplus_remaining
        surplus_remaining = max(0, surplus_remaining - monthly_needed)

        recs.append({
            "name": g.name,
            "target": g.target_amount,
            "years": g.years,
            "priority": g.priority,
            "monthly_needed": monthly_needed,
            "allocation": alloc,
            "feasible": feasible,
        })

    return recs


# ── Gap analysis ──────────────────────────────────────────────────────────────
def gap_analysis(p: UserProfile) -> list[str]:
    gaps = []
    total_monthly_income = p.monthly_income + p.other_income
    monthly_surplus = total_monthly_income - p.monthly_expenses
    recommended_coverage = total_monthly_income * 120

    if p.emergency_fund < p.monthly_expenses * 3:
        months = p.emergency_fund / p.monthly_expenses if p.monthly_expenses > 0 else 0
        needed = p.monthly_expenses * 3 - p.emergency_fund
        gaps.append(
            f"Emergency fund is {months:.1f} months — you need at least 3. "
            f"Top up by Rs.{needed:,.0f}. Park it in a liquid fund or high-yield savings account."
        )

    if not p.has_health_insurance:
        gaps.append(
            "No health insurance. A single hospitalisation can wipe out years of savings. "
            "Get at least Rs.10L individual / Rs.20L family floater cover."
        )

    if (p.dependents > 0
            and p.life_insurance_coverage < recommended_coverage
            and p.savings < recommended_coverage):
        shortfall = recommended_coverage - max(p.life_insurance_coverage, 0)
        gaps.append(
            f"You have {p.dependents} dependent(s) but insufficient life insurance coverage. "
            f"Recommended: Rs.{recommended_coverage:,.0f} (10x annual income). "
            f"Shortfall: Rs.{shortfall:,.0f}. Buy a pure term plan — avoid ULIPs/endowments."
        )

    if monthly_surplus <= 0:
        gaps.append(
            "Monthly expenses equal or exceed income. No capacity to invest until expenses are reduced."
        )

    savings_rate = monthly_surplus / total_monthly_income if total_monthly_income > 0 else 0
    if 0 < savings_rate < 0.10:
        gaps.append(
            f"Savings rate is {savings_rate:.0%}. Target at least 15-20% to build meaningful wealth."
        )

    return gaps


# ── PDF report ────────────────────────────────────────────────────────────────
DARK  = colors.HexColor("#1a1a1a")
MID   = colors.HexColor("#444444")
LIGHT = colors.HexColor("#888888")
RULE  = colors.HexColor("#dddddd")
GREEN = colors.HexColor("#2d7d46")
AMBER = colors.HexColor("#b45309")
RED   = colors.HexColor("#b91c1c")


def score_color(score: int) -> colors.HexColor:
    if score >= 70:
        return GREEN
    elif score >= 45:
        return AMBER
    return RED


def score_label(score: int) -> str:
    if score >= 70:
        return "Healthy"
    elif score >= 45:
        return "Needs Attention"
    return "At Risk"


def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10, leading=14,
                textColor=DARK, spaceAfter=0, spaceBefore=0, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)


def rule():
    return HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=4, spaceBefore=2)


def section(title):
    return [
        Paragraph(title.upper(), S("sec", fontName="Helvetica-Bold", fontSize=8.5,
                                   letterSpacing=1.2, spaceBefore=10, spaceAfter=2)),
        rule(),
    ]


def sp(h=4):
    return Spacer(1, h)


def b(text):
    return Paragraph(f"• {text}", S("bul", fontSize=9.5, leading=13.5,
                                    leftIndent=0, spaceAfter=2, alignment=TA_JUSTIFY))


def generate_pdf(p: UserProfile, health: dict, recs: list[dict],
                 gaps: list[str], output_path: str):
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=14*mm,
        title="Personal Financial Plan",
        author="Financial Planner",
    )

    def rs(n):
        return f"Rs. {n:,.0f}"

    story = []

    # Title
    story.append(Paragraph("Personal Financial Plan",
                            S("title", fontName="Helvetica-Bold", fontSize=20,
                              leading=24, alignment=TA_CENTER)))
    story.append(Paragraph(
        f"Age {p.age}  |  {p.dependents} dependent(s)  |  {p.risk_profile.capitalize()} risk profile",
        S("sub", fontSize=9, textColor=MID, alignment=TA_CENTER, spaceAfter=2)
    ))
    story.append(sp(6))

    # Health score
    total = health["total"]
    col = score_color(total)
    lbl = score_label(total)

    story += section("Financial Health Score")
    story.append(Paragraph(
        f'<font color="{col.hexval()}" size="32"><b>{total}</b></font>'
        f'<font size="14" color="{col.hexval()}"> / 100 -- {lbl}</font>',
        S("score", leading=40, spaceBefore=4, spaceAfter=6)
    ))

    score_rows = [["Category", "Score", "Max"]]
    maxes = {
        "emergency_fund":  ("Emergency Fund",   20),
        "savings_rate":    ("Savings Rate",      20),
        "health_insurance":("Health Insurance",  15),
        "life_insurance":  ("Life Insurance",    15),
        "goal_feasibility":("Goal Feasibility",  30),
    }
    for k, (label, max_v) in maxes.items():
        score_rows.append([label, str(health["scores"][k]), str(max_v)])

    t = Table(score_rows, colWidths=[100*mm, 20*mm, 20*mm])
    t.setStyle(TableStyle([
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  DARK),
        ("TEXTCOLOR",      (0, 1), (-1, -1), MID),
        ("ALIGN",          (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f9f9f9"), colors.white]),
        ("LINEBELOW",      (0, 0), (-1, 0),  0.5, RULE),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(sp(4))

    for k in maxes:
        story.append(b(health["details"][k]))
    story.append(sp(4))

    # Gaps
    if gaps:
        story += section("Priority Gaps to Address First")
        for g in gaps:
            story.append(b(f"ACTION NEEDED: {g}"))
        story.append(sp(4))

    # Goal recommendations
    story += section("Goal Recommendations")

    for rec in recs:
        alloc = rec["allocation"]
        feasibility = "Feasible" if rec["feasible"] else "Stretch -- consider extending timeline"
        col_hex = GREEN.hexval() if rec["feasible"] else AMBER.hexval()

        equity_text = "; ".join(alloc["equity_instruments"][:2]) if alloc["equity"] > 0 else None
        debt_text   = "; ".join(alloc["debt_instruments"][:2])
        gold_text   = alloc["gold_instruments"][0] if alloc["gold"] > 0 else None

        items = [
            Paragraph(
                f'<b>{rec["name"]}</b>  |  '
                f'{rec["priority"].capitalize()} priority  |  '
                f'{rec["years"]} year{"s" if rec["years"] != 1 else ""}',
                S("gh", fontName="Helvetica-Bold", fontSize=10, spaceBefore=8, spaceAfter=2)
            ),
            Paragraph(
                f'Target: <b>{rs(rec["target"])}</b>  |  '
                f'Monthly SIP: <b>{rs(rec["monthly_needed"])}</b>  |  '
                f'<font color="{col_hex}">{feasibility}</font>',
                S("gm", fontSize=9, textColor=MID, spaceAfter=4)
            ),
            b(f"Strategy: {alloc['label']} -- expected return ~{alloc['return']*100:.1f}% p.a."),
            b(
                f"Allocation: {alloc['equity']*100:.0f}% equity, "
                f"{alloc['debt']*100:.0f}% debt, "
                f"{alloc['gold']*100:.0f}% gold, "
                f"{alloc['cash']*100:.0f}% cash/liquid."
            ),
        ]
        if equity_text:
            items.append(b(f"Equity: {equity_text}."))
        items.append(b(f"Debt: {debt_text}."))
        if gold_text:
            items.append(b(f"Gold: {gold_text}."))
        items.append(sp(2))

        story.append(KeepTogether(items))

    # Snapshot
    story += section("Financial Snapshot")
    total_monthly_income = p.monthly_income + p.other_income
    monthly_surplus = total_monthly_income - p.monthly_expenses
    savings_rate = monthly_surplus / total_monthly_income if total_monthly_income > 0 else 0
    total_monthly_needed = sum(r["monthly_needed"] for r in recs)

    snap_rows = [
        ["Monthly salary",          rs(p.monthly_income)],
        ["Other monthly income",    rs(p.other_income)],
        ["Monthly expenses",        rs(p.monthly_expenses)],
        ["Monthly surplus",         rs(monthly_surplus)],
        ["Savings rate",            f"{savings_rate:.0%}"],
        ["Total monthly SIP needed",rs(total_monthly_needed)],
        ["Surplus after goals",     rs(max(0, monthly_surplus - total_monthly_needed))],
        ["Current savings",         rs(p.savings)],
        ["Emergency fund",          rs(p.emergency_fund)],
        ["Existing investments",    rs(p.existing_investments)],
    ]
    snap = Table(snap_rows, colWidths=[100*mm, 60*mm])
    snap.setStyle(TableStyle([
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",      (0, 0), (0, -1),  MID),
        ("TEXTCOLOR",      (1, 0), (1, -1),  DARK),
        ("FONTNAME",       (1, 0), (1, -1),  "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f9f9f9"), colors.white]),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
    ]))
    story.append(snap)
    story.append(sp(6))

    story.append(Paragraph(
        "This plan is generated for informational purposes only and does not constitute financial advice. "
        "Consult a SEBI-registered investment adviser before making investment decisions.",
        S("disc", fontSize=7.5, textColor=LIGHT, alignment=TA_CENTER)
    ))

    doc.build(story)
