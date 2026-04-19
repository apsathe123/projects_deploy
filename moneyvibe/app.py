"""
MoneyVibe v3 — Flask app for Vercel deployment.
Run locally: python app.py
"""

import base64
import json
import os
import tempfile

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, flash, jsonify,
)

from engine import (
    Goal, Loan, UserProfile,
    action_plan, compute_health_score, gap_analysis, generate_pdf,
    goal_recommendations, high_interest_debt, job_loss_buffer_months,
    milestone_badges, monthly_surplus, personal_finance_playbook,
    retirement_summary, risk_profile_from_score, score_label, score_tier,
    stricter_risk_profile, total_debt, total_monthly_emi, total_monthly_needed,
)
from india_profiles import (
    DATA_EFFECTIVE_FROM, DATA_SOURCES, INFLATION_INDIA, LAST_UPDATED,
    RETURN_ASSUMPTIONS, TAX_NOTES, AGE_RISK_NOTES, suggested_risk_profile,
)

_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_dir, "templates"),
    static_folder=os.path.join(_dir, "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET", "moneyvibe-dev-key-change-in-prod")

STEPS = [
    ("about", "About you"),
    ("money", "The money flow"),
    ("assets", "What you own vs owe"),
    ("protect", "Protect your bag"),
    ("risk", "Your risk vibe"),
    ("goals", "Main character goals"),
    ("plan", "Your playbook"),
]

SUGGESTED_GOALS = [
    {"name": "Emergency fund", "target": 50000, "years": 1, "priority": "High", "emoji": "🛡️"},
    {"name": "New phone", "target": 25000, "years": 1, "priority": "Medium", "emoji": "📱"},
    {"name": "Bike / Scooty", "target": 80000, "years": 2, "priority": "Medium", "emoji": "🏍️"},
    {"name": "Trip with friends", "target": 30000, "years": 1, "priority": "Low", "emoji": "✈️"},
    {"name": "First investment", "target": 10000, "years": 1, "priority": "High", "emoji": "📈"},
    {"name": "Laptop / Gadget", "target": 50000, "years": 1, "priority": "Medium", "emoji": "💻"},
    {"name": "Skill course", "target": 15000, "years": 1, "priority": "High", "emoji": "🎓"},
    {"name": "Move-out fund", "target": 100000, "years": 2, "priority": "High", "emoji": "🏠"},
]

GLOSSARY = {
    "SIP": "Systematic Investment Plan — an automated monthly investment, usually into a mutual fund.",
    "EMI": "Equated Monthly Instalment — your fixed monthly loan payment.",
    "PPF": "Public Provident Fund — a 15-year government-backed savings scheme, tax-free.",
    "ELSS": "Equity Linked Savings Scheme — a tax-saving mutual fund with a 3-year lock-in.",
    "NPS": "National Pension System — a retirement scheme with extra tax benefits.",
    "SGB": "Sovereign Gold Bond — RBI-issued gold investment, tax-free at maturity.",
}

DEFAULTS = {
    "age": 22, "dependents": 0,
    "monthly_income": 25000, "other_income": 0, "monthly_expenses": 18000,
    "savings": 0, "emergency_fund": 0,
    "existing_investments": 0, "investment_type": "None",
    "has_health_insurance": False, "life_cover_option": False, "life_insurance_coverage": 0,
    "tax_regime": "new", "chosen_risk_profile": "aggressive",
    "risk_capacity_score": 2, "risk_tolerance_score": 2,
    "inflation_rate_pct": INFLATION_INDIA * 100, "return_adjustment_pct": 0,
    "retirement_age": 60, "life_expectancy": 85,
    "retirement_monthly_expenses": 0, "retirement_corpus": 0,
    "epf_balance": 0, "ppf_balance": 0, "nps_balance": 0,
    "goals": [], "loans": [], "is_student": False,
}


def inr(n: float) -> str:
    if abs(n) >= 1e7:
        return f"₹{n / 1e7:.2f} Cr"
    if abs(n) >= 1e5:
        return f"₹{n / 1e5:.1f} L"
    sign = "-" if n < 0 else ""
    n = abs(n)
    whole = int(round(n))
    if whole < 1000:
        return f"₹{sign}{whole}"
    last3 = whole % 1000
    rest = whole // 1000
    parts = [f"{last3:03d}"]
    while rest:
        parts.append(f"{rest % 100:02d}" if rest >= 100 else str(rest))
        rest //= 100
    return f"₹{sign}{','.join(reversed(parts))}"


def pct(n: float) -> str:
    return f"{n * 100:.1f}%"


def get_field(key, cast=float):
    """Get a field from session with default fallback."""
    val = session.get(key, DEFAULTS.get(key, 0))
    try:
        return cast(val)
    except (ValueError, TypeError):
        return DEFAULTS.get(key, 0)


def get_form_field(key, cast=float, default=0):
    """Safely extract and cast a form value, returning default on bad input."""
    val = request.form.get(key)
    if val is None:
        return default
    try:
        return cast(val)
    except (ValueError, TypeError):
        return default


def ensure_session():
    for key, val in DEFAULTS.items():
        if key not in session:
            session[key] = val


def build_profile() -> UserProfile:
    goals = [
        Goal(name=g["name"], target_amount=float(g["target"]), years=int(g["years"]),
             priority=g["priority"].lower(), target_is_today_value=True,
             existing_allocated=float(g.get("existing_allocated", 0)))
        for g in session.get("goals", [])
    ]
    loans = [
        Loan(name=l["name"], balance=float(l.get("balance", 0)),
             annual_rate=float(l.get("annual_rate", 0)),
             monthly_emi=float(l.get("monthly_emi", 0)))
        for l in session.get("loans", []) if float(l.get("balance", 0)) > 0
    ]
    age = get_field("age", int)
    risk = suggested_risk_profile(age)
    cap = risk_profile_from_score(get_field("risk_capacity_score", int))
    tol = risk_profile_from_score(get_field("risk_tolerance_score", int))
    chosen = session.get("chosen_risk_profile", "aggressive")
    effective = stricter_risk_profile(risk, cap, tol, chosen)

    return UserProfile(
        age=age, dependents=get_field("dependents", int),
        monthly_income=get_field("monthly_income"),
        other_income=get_field("other_income"),
        monthly_expenses=get_field("monthly_expenses"),
        savings=get_field("savings"),
        emergency_fund=get_field("emergency_fund"),
        has_health_insurance=bool(session.get("has_health_insurance", False)),
        life_insurance_coverage=get_field("life_insurance_coverage") if session.get("life_cover_option") else 0,
        existing_investments=get_field("existing_investments"),
        investment_type=session.get("investment_type", "None"),
        risk_profile=effective, goals=goals, loans=loans,
        tax_regime=session.get("tax_regime", "new"),
        risk_capacity_score=get_field("risk_capacity_score", int),
        risk_tolerance_score=get_field("risk_tolerance_score", int),
        auto_allocate_existing=False,
        inflation_rate=get_field("inflation_rate_pct") / 100,
        return_adjustment=get_field("return_adjustment_pct") / 100,
        retirement_age=get_field("retirement_age", int),
        life_expectancy=get_field("life_expectancy", int),
        retirement_monthly_expenses=get_field("retirement_monthly_expenses"),
        retirement_corpus=get_field("retirement_corpus"),
        epf_balance=get_field("epf_balance"),
        ppf_balance=get_field("ppf_balance"),
        nps_balance=get_field("nps_balance"),
    )


# ── Template context helpers ──────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return {
        "steps": STEPS,
        "current_step": _current_step_index(),
        "inr": inr,
        "pct": pct,
        "glossary": GLOSSARY,
        "suggested_goals": SUGGESTED_GOALS,
        "is_student": session.get("is_student", False),
    }


def _current_step_index():
    route = request.endpoint or ""
    for i, (slug, _) in enumerate(STEPS):
        if slug in route:
            return i
    return 0


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    ensure_session()
    return redirect(url_for("about"))


@app.route("/about", methods=["GET", "POST"])
def about():
    ensure_session()
    if request.method == "POST":
        session["age"] = get_form_field("age", int, 22)
        session["dependents"] = get_form_field("dependents", int, 0)
        session["is_student"] = "is_student" in request.form
        return redirect(url_for("money"))
    return render_template("step_about.html", s=session)


@app.route("/money", methods=["GET", "POST"])
def money():
    ensure_session()
    if request.method == "POST":
        session["monthly_income"] = get_form_field("monthly_income")
        session["other_income"] = get_form_field("other_income")
        session["monthly_expenses"] = get_form_field("monthly_expenses")
        return redirect(url_for("assets"))
    return render_template("step_money.html", s=session)


@app.route("/assets", methods=["GET", "POST"])
def assets():
    ensure_session()
    if request.method == "POST":
        session["savings"] = get_form_field("savings")
        session["emergency_fund"] = get_form_field("emergency_fund")
        session["existing_investments"] = get_form_field("existing_investments")
        session["investment_type"] = request.form.get("investment_type", "None")
        # Parse loans from form
        loans = []
        i = 0
        while f"loan_name_{i}" in request.form:
            loans.append({
                "name": request.form.get(f"loan_name_{i}", "Loan"),
                "balance": get_form_field(f"loan_balance_{i}"),
                "annual_rate": get_form_field(f"loan_rate_{i}") / 100,
                "monthly_emi": get_form_field(f"loan_emi_{i}"),
            })
            i += 1
        session["loans"] = loans
        return redirect(url_for("protect"))
    return render_template("step_assets.html", s=session)


@app.route("/protect", methods=["GET", "POST"])
def protect():
    ensure_session()
    if request.method == "POST":
        session["has_health_insurance"] = "has_health_insurance" in request.form
        session["life_cover_option"] = "life_cover_option" in request.form
        session["life_insurance_coverage"] = get_form_field("life_insurance_coverage")
        return redirect(url_for("risk"))
    return render_template("step_protect.html", s=session)


@app.route("/risk", methods=["GET", "POST"])
def risk():
    ensure_session()
    if request.method == "POST":
        session["risk_capacity_score"] = get_form_field("risk_capacity_score", int, 2)
        session["risk_tolerance_score"] = get_form_field("risk_tolerance_score", int, 2)
        session["tax_regime"] = request.form.get("tax_regime", "new")
        session["chosen_risk_profile"] = request.form.get("chosen_risk_profile", "aggressive")
        session["retirement_age"] = get_form_field("retirement_age", int, 60)
        session["life_expectancy"] = get_form_field("life_expectancy", int, 85)
        session["retirement_monthly_expenses"] = get_form_field("retirement_monthly_expenses")
        session["retirement_corpus"] = get_form_field("retirement_corpus")
        session["inflation_rate_pct"] = get_form_field("inflation_rate_pct", float, 5.5)
        session["epf_balance"] = get_form_field("epf_balance")
        session["ppf_balance"] = get_form_field("ppf_balance")
        session["nps_balance"] = get_form_field("nps_balance")
        return redirect(url_for("goals"))
    age = get_field("age", int)
    age_risk = suggested_risk_profile(age)
    return render_template("step_risk.html", s=session, age_risk=age_risk, age_risk_notes=AGE_RISK_NOTES)


@app.route("/goals", methods=["GET", "POST"])
def goals():
    ensure_session()
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "next":
            return redirect(url_for("plan"))
        elif action.startswith("add_suggested_"):
            try:
                idx = int(action.split("_")[-1])
            except (ValueError, TypeError):
                idx = -1
            if 0 <= idx < len(SUGGESTED_GOALS):
                sg = SUGGESTED_GOALS[idx]
                g_list = session.get("goals", [])
                if not any(g["name"] == sg["name"] for g in g_list):
                    g_list.append({"name": sg["name"], "target": sg["target"], "years": sg["years"], "priority": sg["priority"]})
                    session["goals"] = g_list
        elif action == "add_custom":
            g_list = session.get("goals", [])
            g_list.append({"name": "My goal", "target": 20000, "years": 1, "priority": "Medium"})
            session["goals"] = g_list
        elif action.startswith("remove_"):
            try:
                idx = int(action.split("_")[-1])
            except (ValueError, TypeError):
                idx = -1
            g_list = session.get("goals", [])
            if 0 <= idx < len(g_list):
                g_list.pop(idx)
                session["goals"] = g_list
        elif action == "update_goals":
            g_list = []
            i = 0
            while f"goal_name_{i}" in request.form:
                g_list.append({
                    "name": request.form.get(f"goal_name_{i}", "Goal"),
                    "target": get_form_field(f"goal_target_{i}", float, 20000),
                    "years": get_form_field(f"goal_years_{i}", int, 1),
                    "priority": request.form.get(f"goal_priority_{i}", "Medium"),
                })
                i += 1
            session["goals"] = g_list
            return redirect(url_for("plan"))
        return redirect(url_for("goals"))
    return render_template("step_goals.html", s=session, suggested=SUGGESTED_GOALS)


@app.route("/plan")
def plan():
    ensure_session()
    if not session.get("goals"):
        flash("Add at least one goal first.")
        return redirect(url_for("goals"))
    if get_field("monthly_income") <= 0 and get_field("other_income") <= 0:
        flash("Enter your income before generating a plan.")
        return redirect(url_for("money"))
    if get_field("retirement_age", int) <= get_field("age", int):
        flash("Retirement age must be greater than your current age.")
        return redirect(url_for("risk"))
    if get_field("life_expectancy", int) <= get_field("retirement_age", int):
        flash("Life expectancy must be greater than retirement age.")
        return redirect(url_for("risk"))

    profile = build_profile()
    recs = goal_recommendations(profile)
    health = compute_health_score(profile, recs)
    gaps = gap_analysis(profile)
    actions = action_plan(profile, recs, gaps)
    playbook = personal_finance_playbook(profile, health, recs, gaps)
    badges = milestone_badges(profile, recs)
    ret = retirement_summary(profile) if not session.get("is_student") else None
    tier = score_tier(health["total"])
    surplus = monthly_surplus(profile)
    needed = total_monthly_needed(recs)
    buffer_mo = job_loss_buffer_months(profile)

    return render_template("results.html",
        profile=profile, recs=recs, health=health, gaps=gaps,
        actions=actions, playbook=playbook, badges=badges,
        retirement=ret, tier=tier, surplus=surplus, needed=needed,
        buffer_months=buffer_mo, suggested=SUGGESTED_GOALS,
        score_label=score_label, alloc_bar_data=_alloc_bar_data,
    )


def _alloc_bar_data(alloc):
    return [
        (alloc["equity"], "equity", f"{alloc['equity']*100:.0f}% Equity"),
        (alloc["debt"], "debt", f"{alloc['debt']*100:.0f}% Debt"),
        (alloc["gold"], "gold", f"{alloc['gold']*100:.0f}% Gold"),
        (alloc["cash"], "cash", f"{alloc['cash']*100:.0f}% Cash"),
    ]


@app.route("/download-pdf")
def download_pdf():
    ensure_session()
    profile = build_profile()
    recs = goal_recommendations(profile)
    health = compute_health_score(profile, recs)
    gaps = gap_analysis(profile)
    actions = action_plan(profile, recs, gaps)
    playbook = personal_finance_playbook(profile, health, recs, gaps)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp_path = tmp.name
    generate_pdf(profile, health, recs, gaps, tmp_path, actions, playbook)
    return send_file(tmp_path, as_attachment=True, download_name="MoneyVibe_Plan.pdf", mimetype="application/pdf")


@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
