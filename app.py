"""
Personal Financial Planner -- Streamlit app.
Run with: streamlit run app.py --server.headless true
"""

import streamlit as st
import os
import tempfile
from engine import (
    UserProfile, Goal,
    compute_health_score, goal_recommendations, gap_analysis, generate_pdf,
    score_label,
)
from india_profiles import suggested_risk_profile, AGE_RISK_NOTES

st.set_page_config(
    page_title="Personal Financial Planner",
    page_icon="📊",
    layout="centered",
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def inr(n: float) -> str:
    """Format a number in Indian notation: Cr / L / raw."""
    if abs(n) >= 1e7:
        return f"₹{n/1e7:.2f} Cr"
    elif abs(n) >= 1e5:
        return f"₹{n/1e5:.1f} L"
    else:
        return f"₹{n:,.0f}"


def alloc_bar(equity: float, debt: float, gold: float, cash: float) -> str:
    """Render a coloured stacked bar for asset allocation."""
    segments = [
        (equity, "#3b82f6", f"{equity*100:.0f}% Equity"),
        (debt,   "#22c55e", f"{debt*100:.0f}% Debt"),
        (gold,   "#f59e0b", f"{gold*100:.0f}% Gold"),
        (cash,   "#94a3b8", f"{cash*100:.0f}% Cash"),
    ]
    bar = "".join(
        f"<div style='width:{pct*100:.0f}%;background:{col};height:100%' title='{lbl}'></div>"
        for pct, col, lbl in segments if pct > 0
    )
    legend = "&nbsp;&nbsp;".join(
        f"<span style='color:{col}'>■</span> {lbl}"
        for pct, col, lbl in segments if pct > 0
    )
    return (
        f"<div style='display:flex;height:16px;border-radius:4px;overflow:hidden;"
        f"margin:6px 0 4px 0'>{bar}</div>"
        f"<div style='font-size:11px;color:#666;margin-bottom:8px'>{legend}</div>"
    )


# ── Suggested goals ───────────────────────────────────────────────────────────
SUGGESTED_GOALS = [
    {"name": "Retirement",           "target": 30000000, "years": 30, "priority": "High"},
    {"name": "House (Down Payment)", "target": 3000000,  "years": 7,  "priority": "High"},
    {"name": "Kids Education",       "target": 2500000,  "years": 15, "priority": "High"},
    {"name": "Wedding",              "target": 2000000,  "years": 5,  "priority": "High"},
    {"name": "Car",                  "target": 800000,   "years": 3,  "priority": "Medium"},
    {"name": "Travel Fund",          "target": 300000,   "years": 2,  "priority": "Low"},
    {"name": "College Fund",         "target": 2000000,  "years": 18, "priority": "Medium"},
    {"name": "Having Kids",          "target": 500000,   "years": 3,  "priority": "Medium"},
]

# ── Session state defaults ────────────────────────────────────────────────────
if "goals" not in st.session_state:
    st.session_state.goals = []
if "plan" not in st.session_state:
    st.session_state.plan = None
if "last_added" not in st.session_state:
    st.session_state.last_added = -1

# ═════════════════════════════════════════════════════════════════════════════
# INPUT FORM
# ═════════════════════════════════════════════════════════════════════════════
st.title("📊 Personal Financial Planner")
st.caption("Fill in your details below and generate your personalised India-specific financial plan.")

# ── 1. About You ──────────────────────────────────────────────────────────────
st.header("1. About You")
col1, col2 = st.columns(2)
with col1:
    age = st.number_input("Your age", min_value=18, max_value=80, value=30)
with col2:
    dependents = st.selectbox(
        "Number of dependents",
        options=list(range(7)),
        index=0,
        help="Spouse, children, or parents who rely on your income.",
    )

# ── 2. Income & Expenses ──────────────────────────────────────────────────────
st.header("2. Income & Expenses")
col1, col2 = st.columns(2)
with col1:
    monthly_income = st.number_input(
        "Monthly take-home salary (₹)", min_value=0.0, value=100000.0, step=5000.0)
    other_income = st.number_input(
        "Other monthly income (₹)", min_value=0.0, value=0.0, step=1000.0,
        help="Rental, freelance, dividends, business income, etc.")
with col2:
    monthly_expenses = st.number_input(
        "Monthly expenses (₹)", min_value=0.0, value=60000.0, step=5000.0,
        help="Rent, food, transport, EMIs, subscriptions — everything.")

total_income = monthly_income + other_income
surplus = total_income - monthly_expenses
surplus_pct = surplus / total_income if total_income > 0 else 0
col1, col2, col3 = st.columns(3)
col1.metric("Total monthly income", inr(total_income))
col2.metric("Monthly surplus", inr(surplus),
            delta=f"{surplus_pct:.0%} savings rate" if total_income > 0 else None)
col3.metric("Annual income", inr(total_income * 12))

# ── 3. Current Financial Position ─────────────────────────────────────────────
st.header("3. Current Financial Position")
col1, col2 = st.columns(2)
with col1:
    savings = st.number_input(
        "Savings / liquid cash (₹)", min_value=0.0, value=200000.0, step=10000.0,
        help="Total liquid cash across savings accounts and FDs.")
    emergency_fund = st.number_input(
        "Emergency fund (₹)", min_value=0.0, value=0.0, step=10000.0,
        help="Cash set aside specifically for emergencies — separate from savings. Enter 0 if none.")
with col2:
    existing_investments = st.number_input(
        "Existing investments (₹)", min_value=0.0, value=0.0, step=10000.0,
        help="Current market value of mutual funds, stocks, PPF, NPS, etc.")
    investment_type = st.selectbox(
        "Type of existing investments",
        ["None", "Mutual Funds", "Stocks / ETFs", "Pension / PPF / EPF",
         "Property", "Bonds / FD", "Mixed"])

# ── 4. Protection ─────────────────────────────────────────────────────────────
st.header("4. Protection")
col1, col2 = st.columns(2)

with col1:
    has_health_insurance = st.radio(
        "Health insurance?", ["Yes", "No"], horizontal=True) == "Yes"
    if not has_health_insurance:
        st.caption("Minimum recommended: ₹10L individual / ₹20L family floater.")

with col2:
    recommended_coverage = total_income * 120
    life_cover_option = st.radio("Life insurance (term plan)?", ["Yes", "No"], horizontal=True)
    if life_cover_option == "Yes":
        life_insurance_coverage = st.number_input(
            "Sum assured (₹)", min_value=0.0,
            value=float(recommended_coverage), step=500000.0,
            help=f"Recommended: {inr(recommended_coverage)} (10x annual income)")
        gap = recommended_coverage - life_insurance_coverage
        if gap > 0:
            st.caption(f"Below recommended by {inr(gap)}.")
        else:
            st.caption("Meets the 10x annual income benchmark.")
    else:
        life_insurance_coverage = 0.0
        if dependents > 0:
            st.caption(f"With {dependents} dependent(s), recommended: {inr(recommended_coverage)}.")

# ── 5. Risk Profile ───────────────────────────────────────────────────────────
st.header("5. Risk Profile")

suggestion = suggested_risk_profile(age)
risk_options = ["Conservative", "Moderate", "Aggressive"]
risk_profile = st.radio(
    "Choose your risk profile",
    risk_options,
    index=risk_options.index(suggestion.capitalize()),
    horizontal=True,
).lower()

profile_info = {
    "conservative": (
        "Capital preservation first. Short-term goals: FDs and liquid funds. "
        "Long-term goals: 50-60% equity (Nifty 50 index), rest in PPF and debt funds. "
        "Suitable if you cannot tolerate seeing your portfolio fall 20-30% even temporarily."
    ),
    "moderate": (
        "Balanced growth across equity, debt, and gold. Long-term: 65-75% equity "
        "(Nifty 50 + Next 50 + mid-cap index), PPF maxed out, Sovereign Gold Bonds. "
        "Right for most working professionals with a 5+ year horizon."
    ),
    "aggressive": (
        "Equity-heavy for maximum compounding. Long-term: 80-85% equity "
        "(Nifty 50, Nifty Next 50, Midcap 150 index funds), NPS Tier-1, SGBs. "
        "Suitable if you are under 40 and can stay invested through 30-50% drawdowns."
    ),
}
age_note = AGE_RISK_NOTES[suggestion]
st.info(
    f"**Suggested for age {age}: {suggestion.capitalize()}** — {age_note}\n\n"
    f"**{risk_profile.capitalize()} profile:** {profile_info[risk_profile]}"
)

# ── 6. Financial Goals ────────────────────────────────────────────────────────
st.header("6. Financial Goals")

added_names = {g["name"] for g in st.session_state.goals}

st.markdown("**Quick add a goal:**")
cols = st.columns(4)
for i, sg in enumerate(SUGGESTED_GOALS):
    already_added = sg["name"] in added_names
    with cols[i % 4]:
        if st.button(
            f"{'✓' if already_added else '+'} {sg['name']}",
            key=f"sg_{i}",
            disabled=already_added,
            help=f"Target: {inr(sg['target'])} in {sg['years']} years",
        ):
            st.session_state.goals.append({
                "name": sg["name"],
                "target": float(sg["target"]),
                "years": sg["years"],
                "priority": sg["priority"],
            })
            st.session_state.last_added = len(st.session_state.goals) - 1
            st.rerun()

st.divider()

if not st.session_state.goals:
    st.caption("No goals added yet. Use the quick-add buttons above or add a custom goal below.")

for i, g in enumerate(st.session_state.goals):
    is_new = (i == st.session_state.last_added)
    with st.expander(f"Goal {i+1}: {g['name']} — {inr(g['target'])} in {g['years']} yrs",
                     expanded=is_new):
        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
        with col1:
            st.session_state.goals[i]["name"] = st.text_input(
                "Goal name", value=g["name"], key=f"name_{i}")
        with col2:
            st.session_state.goals[i]["target"] = st.number_input(
                "Target (₹)", min_value=0.0, value=float(g["target"]),
                step=10000.0, key=f"target_{i}")
        with col3:
            st.session_state.goals[i]["years"] = st.number_input(
                "Years", min_value=1, max_value=50,
                value=int(g["years"]), key=f"years_{i}")
        with col4:
            st.session_state.goals[i]["priority"] = st.selectbox(
                "Priority", ["High", "Medium", "Low"],
                index=["High", "Medium", "Low"].index(g["priority"]),
                key=f"priority_{i}")
        if st.button("Remove goal", key=f"remove_{i}"):
            st.session_state.goals.pop(i)
            st.session_state.last_added = -1
            st.rerun()

if st.button("+ Add custom goal"):
    st.session_state.goals.append(
        {"name": "My Goal", "target": 500000.0, "years": 5, "priority": "Medium"})
    st.session_state.last_added = len(st.session_state.goals) - 1
    st.rerun()

# ── Generate ──────────────────────────────────────────────────────────────────
st.divider()

btn_label = "Regenerate Plan" if st.session_state.plan else "Generate My Financial Plan"
generate = st.button(btn_label, type="primary", use_container_width=True)

if generate:
    if monthly_income <= 0:
        st.error("Please enter a valid monthly salary.")
    elif monthly_expenses <= 0:
        st.error("Please enter a valid monthly expenses figure.")
    elif not st.session_state.goals:
        st.error("Please add at least one goal.")
    else:
        with st.spinner("Building your financial plan..."):
            goals = [
                Goal(
                    name=g["name"],
                    target_amount=g["target"],
                    years=g["years"],
                    priority=g["priority"].lower(),
                )
                for g in st.session_state.goals
            ]
            profile = UserProfile(
                age=age,
                dependents=dependents,
                monthly_income=monthly_income,
                other_income=other_income,
                monthly_expenses=monthly_expenses,
                savings=savings,
                emergency_fund=emergency_fund,
                has_health_insurance=has_health_insurance,
                life_insurance_coverage=life_insurance_coverage,
                existing_investments=existing_investments,
                investment_type=investment_type,
                risk_profile=risk_profile,
                goals=goals,
            )
            health = compute_health_score(profile)
            recs   = goal_recommendations(profile)
            gaps   = gap_analysis(profile)
            st.session_state.plan = {
                "health": health, "recs": recs, "gaps": gaps, "profile": profile,
            }

# ═════════════════════════════════════════════════════════════════════════════
# RESULTS  (persisted in session_state — survive reruns)
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.plan:
    plan    = st.session_state.plan
    health  = plan["health"]
    recs    = plan["recs"]
    gaps    = plan["gaps"]
    profile = plan["profile"]

    st.divider()
    st.header("Your Financial Plan")

    # ── Financial Snapshot (first — context before score) ────────────────────
    total_needed = sum(r["monthly_needed"] for r in recs)
    left_over    = surplus - total_needed

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Monthly surplus",     inr(surplus))
    col2.metric("Monthly SIP needed",  inr(total_needed))
    col3.metric("Left after goals",    inr(max(0, left_over)),
                delta=None if left_over >= 0 else f"{inr(abs(left_over))} shortfall",
                delta_color="normal" if left_over >= 0 else "inverse")
    col4.metric("Savings rate",
                f"{surplus_pct:.0%}" if total_income > 0 else "N/A")

    # ── Health Score ─────────────────────────────────────────────────────────
    st.subheader("Financial Health Score")
    total_score = health["total"]
    label  = score_label(total_score)
    colour = "#2d7d46" if total_score >= 70 else "#b45309" if total_score >= 45 else "#b91c1c"

    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown(
            f"<div style='text-align:center;padding:20px 16px;border-radius:10px;"
            f"border:2px solid {colour};margin-top:4px'>"
            f"<span style='font-size:52px;font-weight:bold;color:{colour}'>{total_score}</span>"
            f"<br><span style='font-size:11px;color:#888'>out of 100</span>"
            f"<br><span style='font-size:14px;font-weight:600;color:{colour}'>{label}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with col2:
        cats = {
            "Emergency Fund":   ("emergency_fund",   20),
            "Savings Rate":     ("savings_rate",     20),
            "Health Insurance": ("health_insurance", 15),
            "Life Insurance":   ("life_insurance",   15),
            "Goal Feasibility": ("goal_feasibility", 30),
        }
        for label_text, (key, max_v) in cats.items():
            s   = health["scores"][key]
            pct = int(s / max_v * 100)
            bar_col = "#2d7d46" if pct >= 70 else "#b45309" if pct >= 40 else "#b91c1c"
            st.markdown(
                f"<div style='margin-bottom:8px'>"
                f"<div style='display:flex;justify-content:space-between;font-size:12px'>"
                f"<span>{label_text}</span>"
                f"<span style='color:{bar_col};font-weight:600'>{s}/{max_v}</span></div>"
                f"<div style='background:#eee;border-radius:4px;height:8px;margin-top:3px'>"
                f"<div style='background:{bar_col};width:{pct}%;height:8px;border-radius:4px'>"
                f"</div></div></div>",
                unsafe_allow_html=True,
            )

    with st.expander("What drives your score?"):
        for label_text, (key, _) in cats.items():
            st.markdown(f"**{label_text}:** {health['details'][key]}")

    # ── Priority Gaps ────────────────────────────────────────────────────────
    if gaps:
        st.subheader("Action Items")
        for g in gaps:
            st.warning(g, icon="⚠️")

    # ── Goal Recommendations ─────────────────────────────────────────────────
    st.subheader(f"Goal Recommendations ({len(recs)} goals)")

    for rec in recs:
        alloc   = rec["allocation"]
        feasible = rec["feasible"]
        status  = "✅ Feasible" if feasible else "⚠️ Stretch"
        header  = (
            f"{status}  ·  **{rec['name']}**  ·  "
            f"{inr(rec['monthly_needed'])}/mo  ·  "
            f"{rec['years']} yrs  ·  {rec['priority'].capitalize()} priority"
        )

        with st.expander(header, expanded=False):
            col1, col2, col3 = st.columns(3)
            col1.metric("Target",        inr(rec["target"]))
            col2.metric("Monthly SIP",   inr(rec["monthly_needed"]))
            col3.metric("Strategy",      alloc["label"])

            st.markdown(f"**Expected return:** ~{alloc['return']*100:.1f}% p.a.")
            st.markdown(alloc_bar(alloc["equity"], alloc["debt"], alloc["gold"], alloc["cash"]),
                        unsafe_allow_html=True)
            st.caption(alloc["rationale"])

            if alloc["equity"] > 0:
                st.markdown("**Equity**")
                for inst in alloc["equity_instruments"]:
                    st.markdown(f"- {inst}")

            st.markdown("**Debt**")
            for inst in alloc["debt_instruments"]:
                st.markdown(f"- {inst}")

            if alloc["gold"] > 0:
                st.markdown("**Gold**")
                for inst in alloc["gold_instruments"]:
                    st.markdown(f"- {inst}")

            if alloc["cash"] > 0:
                st.markdown("**Cash / Liquid**")
                for inst in alloc["cash_instruments"][:2]:
                    st.markdown(f"- {inst}")

            if not feasible:
                st.info(
                    "This goal exceeds your current monthly surplus. "
                    "Consider extending the timeline or reducing the target."
                )

    # ── PDF Download ─────────────────────────────────────────────────────────
    st.divider()
    with st.spinner("Preparing PDF..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp_path = tmp.name
        generate_pdf(profile, health, recs, gaps, tmp_path)
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)

    st.download_button(
        label="⬇ Download PDF Report",
        data=pdf_bytes,
        file_name="Personal_Financial_Plan.pdf",
        mime="application/pdf",
        use_container_width=True,
        type="primary",
    )
    st.caption(
        "This plan is for informational purposes only and does not constitute financial advice. "
        "Consult a SEBI-registered investment adviser before making investment decisions."
    )
