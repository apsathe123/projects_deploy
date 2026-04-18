"""
Personal Financial Planner -- Streamlit app.
Run with: streamlit run app.py --server.headless true
"""

import base64
import json
import os
import re
import tempfile

import gspread
from google.oauth2.service_account import Credentials
import resend
import streamlit as st

from engine import (
    Goal,
    Loan,
    UserProfile,
    action_plan,
    compute_health_score,
    gap_analysis,
    generate_pdf,
    goal_recommendations,
    high_interest_debt,
    job_loss_buffer_months,
    monthly_surplus,
    personal_finance_playbook,
    retirement_summary,
    risk_profile_from_score,
    score_label,
    stricter_risk_profile,
    total_debt,
    total_monthly_emi,
    total_monthly_needed,
)
from india_profiles import (
    DATA_EFFECTIVE_FROM,
    DATA_SOURCES,
    INFLATION_INDIA,
    LAST_UPDATED,
    RETURN_ASSUMPTIONS,
    TAX_NOTES,
    AGE_RISK_NOTES,
    suggested_risk_profile,
)


st.set_page_config(
    page_title="Personal Financial Planner",
    page_icon="📊",
    layout="centered",
)


SUGGESTED_GOALS = [
    {"name": "Retirement", "target": 30000000, "years": 30, "priority": "High"},
    {"name": "House (Down Payment)", "target": 3000000, "years": 7, "priority": "High"},
    {"name": "Kids Education", "target": 2500000, "years": 15, "priority": "High"},
    {"name": "Wedding", "target": 2000000, "years": 5, "priority": "High"},
    {"name": "Parents' Medical Fund", "target": 1500000, "years": 5, "priority": "High"},
    {"name": "Maternity & Early Childcare", "target": 1000000, "years": 3, "priority": "Medium"},
    {"name": "Car", "target": 800000, "years": 3, "priority": "Medium"},
    {"name": "Emergency Buffer", "target": 500000, "years": 2, "priority": "High"},
]

STEPS = [
    "About You",
    "Money In & Out",
    "Assets & Loans",
    "Safety Net",
    "Risk & Assumptions",
    "Goals",
    "Your Plan",
]


def inr(n: float) -> str:
    if abs(n) >= 1e7:
        return f"₹{n / 1e7:.2f} Cr"
    if abs(n) >= 1e5:
        return f"₹{n / 1e5:.1f} L"
    # Indian grouping: ₹1,00,000 not ₹100,000
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


def truncate(text: str, max_len: int = 42) -> str:
    text = text.strip() or "Untitled goal"
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def pct(n: float) -> str:
    return f"{n * 100:.1f}%"


def encode_state(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_state(raw: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def serializable_state() -> dict:
    keys = [
        "age",
        "dependents",
        "monthly_income",
        "other_income",
        "monthly_expenses",
        "savings",
        "emergency_fund",
        "existing_investments",
        "investment_type",
        "has_health_insurance",
        "life_cover_option",
        "life_insurance_coverage",
        "tax_regime",
        "chosen_risk_profile",
        "risk_capacity_score",
        "risk_tolerance_score",
        "auto_allocate_existing",
        "inflation_rate_pct",
        "return_adjustment_pct",
        "retirement_age",
        "life_expectancy",
        "retirement_monthly_expenses",
        "retirement_corpus",
        "epf_balance",
        "ppf_balance",
        "nps_balance",
    ]
    return {
        "fields": {k: st.session_state.get(k) for k in keys if k in st.session_state},
        "goals": st.session_state.get("goals", []),
        "loans": st.session_state.get("loans", []),
    }


def sync_query_params():
    st.query_params["p"] = encode_state(serializable_state())


def load_query_params_once():
    if st.session_state.get("loaded_from_query"):
        return
    state = decode_state(st.query_params.get("p", ""))
    for key, value in state.get("fields", {}).items():
        if value is not None:
            st.session_state[key] = value
    if state.get("goals"):
        st.session_state.goals = state["goals"]
    if state.get("loans"):
        st.session_state.loans = state["loans"]
    st.session_state.loaded_from_query = True


def _all_field_defaults() -> dict:
    """Single source of truth for all session state defaults."""
    return {
        "age": 30,
        "dependents": 0,
        "monthly_income": 50000.0,
        "other_income": 0.0,
        "monthly_expenses": 30000.0,
        "savings": 0.0,
        "emergency_fund": 0.0,
        "existing_investments": 0.0,
        "investment_type": "None",
        "has_health_insurance": "Yes",
        "life_cover_option": "No",
        "life_insurance_coverage": 0.0,
        "tax_regime": "New",
        "chosen_risk_profile": "Moderate",
        "effective_risk_profile": "moderate",
        "risk_capacity_score": 2,
        "risk_tolerance_score": 2,
        "auto_allocate_existing": False,
        "inflation_rate_pct": INFLATION_INDIA * 100,
        "return_adjustment_pct": 0.0,
        "retirement_age": 60,
        "life_expectancy": 85,
        "retirement_monthly_expenses": 0.0,
        "retirement_corpus": 0.0,
        "epf_balance": 0.0,
        "ppf_balance": 0.0,
        "nps_balance": 0.0,
        "goals": [],
        "loans": [],
        "plan": None,
    }


def ensure_defaults():
    defaults = {
        **_all_field_defaults(),
        "current_step": 0,
        "last_added": -1,
        "confirm_remove_goal": None,
        "reading_theme": "System",
        "text_size": "Comfortable",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def inject_css(theme: str, font_size: str):
    font_scale = {"Comfortable": "1rem", "Large": "1.08rem", "Extra large": "1.16rem"}.get(font_size, "1rem")
    themes = {
        "System": {
            "scheme": "normal",
            "bg": "transparent",
            "surface": "transparent",
            "text": "inherit",
            "muted": "#64748b",
            "border": "rgba(148, 163, 184, 0.24)",
        },
        "Light": {
            "scheme": "light",
            "bg": "#fafafa",
            "surface": "#ffffff",
            "text": "#111827",
            "muted": "#64748b",
            "border": "rgba(15, 23, 42, 0.14)",
        },
        "Dark": {
            "scheme": "dark",
            "bg": "#111827",
            "surface": "#1f2937",
            "text": "#f9fafb",
            "muted": "#cbd5e1",
            "border": "rgba(226, 232, 240, 0.20)",
        },
        "Sepia": {
            "scheme": "light",
            "bg": "#f8f1e3",
            "surface": "#fffaf0",
            "text": "#241f18",
            "muted": "#725f46",
            "border": "rgba(112, 84, 48, 0.22)",
        },
    }
    palette = themes.get(theme, themes["System"])
    themed_surface_css = ""
    if theme != "System":
        themed_surface_css = f"""
        .stApp,
        [data-testid="stAppViewContainer"] {{
            background: {palette["bg"]};
            color: {palette["text"]};
        }}
        [data-testid="stSidebar"],
        [data-testid="stSidebarContent"] {{
            background: {palette["surface"]};
            color: {palette["text"]};
        }}
        .stApp p,
        .stApp li,
        .stApp label,
        .stApp span,
        .stApp h1,
        .stApp h2,
        .stApp h3,
        .stApp h4,
        .stApp h5,
        .stApp h6,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span {{
            color: {palette["text"]};
        }}
        .stApp input,
        .stApp textarea,
        .stApp [data-baseweb="select"] > div {{
            background-color: {palette["surface"]};
            color: {palette["text"]};
            border-color: {palette["border"]};
        }}
        """
    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: {palette["scheme"]};
            --pfp-font-size: {font_scale};
            --pfp-good: #166534;
            --pfp-warn: #a16207;
            --pfp-bad: #b91c1c;
            --pfp-muted: {palette["muted"]};
            --pfp-track: {palette["border"]};
            --pfp-equity: #2563eb;
            --pfp-debt: #16a34a;
            --pfp-gold: #ca8a04;
            --pfp-cash: #64748b;
        }}
        .stApp,
        [data-testid="stSidebar"] {{
            font-size: var(--pfp-font-size);
        }}
        .stApp [data-testid="stMarkdownContainer"] p,
        .stApp [data-testid="stMarkdownContainer"] li,
        .stApp label,
        .stApp input,
        .stApp textarea,
        .stApp button,
        .stApp [data-baseweb="select"] span,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] button,
        [data-testid="stSidebar"] [data-baseweb="select"] span {{
            font-size: var(--pfp-font-size) !important;
        }}
        {themed_surface_css}
        @media (prefers-color-scheme: dark) {{
            :root {{ --pfp-track: rgba(226, 232, 240, 0.20); }}
        }}
        .pfp-score {{
            text-align:center; padding:20px 16px; border-radius:8px;
            border:2px solid currentColor; margin-top:4px;
        }}
        .pfp-score-num {{ font-size:52px; font-weight:700; line-height:1; }}
        .pfp-score-sub {{ font-size:11px; color:var(--pfp-muted); }}
        .pfp-bar-track {{ background:var(--pfp-track); border-radius:4px; height:8px; margin-top:3px; }}
        .pfp-bar-fill {{ height:8px; border-radius:4px; }}
        .alloc-bar {{ display:flex; height:16px; border-radius:4px; overflow:hidden; margin:6px 0 4px 0; }}
        .alloc-legend {{ font-size:11px; color:var(--pfp-muted); margin-bottom:8px; }}
        .alloc-equity {{ background:var(--pfp-equity); }}
        .alloc-debt {{ background:var(--pfp-debt); }}
        .alloc-gold {{ background:var(--pfp-gold); }}
        .alloc-cash {{ background:var(--pfp-cash); }}
        .small-note {{ color:var(--pfp-muted); font-size:0.9rem; }}
        .pfp-card {{
            border: 1px solid var(--pfp-track); border-radius: 12px;
            padding: 16px; margin: 8px 0;
        }}
        .tag-good {{ background: rgba(22,101,52,0.12); color: var(--pfp-good); padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
        .tag-warn {{ background: rgba(161,98,7,0.12); color: var(--pfp-warn); padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def alloc_bar(equity: float, debt: float, gold: float, cash: float) -> str:
    segments = [
        (equity, "alloc-equity", f"{equity * 100:.0f}% Equity"),
        (debt, "alloc-debt", f"{debt * 100:.0f}% Debt"),
        (gold, "alloc-gold", f"{gold * 100:.0f}% Gold"),
        (cash, "alloc-cash", f"{cash * 100:.0f}% Cash"),
    ]
    bar = "".join(
        f"<div class='{klass}' style='width:{share * 100:.0f}%' title='{label}'></div>"
        for share, klass, label in segments
        if share > 0
    )
    legend = "&nbsp;&nbsp;".join(
        f"<span class='{klass}'>■</span> {label}" for share, klass, label in segments if share > 0
    )
    return f"<div class='alloc-bar'>{bar}</div><div class='alloc-legend'>{legend}</div>"


def build_profile() -> UserProfile:
    goals = [
        Goal(
            name=g["name"],
            target_amount=float(g["target"]),
            years=int(g["years"]),
            priority=g["priority"].lower(),
            target_is_today_value=bool(g.get("target_is_today_value", True)),
            existing_allocated=float(g.get("existing_allocated", 0.0)),
        )
        for g in st.session_state.goals
    ]
    loans = [
        Loan(
            name=l["name"],
            balance=float(l.get("balance", 0.0)),
            annual_rate=float(l.get("annual_rate", 0.0)),
            monthly_emi=float(l.get("monthly_emi", 0.0)),
        )
        for l in st.session_state.loans
        if float(l.get("balance", 0.0)) > 0
    ]
    return UserProfile(
        age=int(st.session_state.age),
        dependents=int(st.session_state.dependents),
        monthly_income=float(st.session_state.monthly_income),
        other_income=float(st.session_state.other_income),
        monthly_expenses=float(st.session_state.monthly_expenses),
        savings=float(st.session_state.savings),
        emergency_fund=float(st.session_state.emergency_fund),
        has_health_insurance=st.session_state.has_health_insurance == "Yes",
        life_insurance_coverage=float(st.session_state.life_insurance_coverage)
        if st.session_state.life_cover_option == "Yes"
        else 0.0,
        existing_investments=float(st.session_state.existing_investments),
        investment_type=st.session_state.investment_type,
        risk_profile=st.session_state.effective_risk_profile,
        goals=goals,
        loans=loans,
        tax_regime=st.session_state.tax_regime.lower(),
        risk_capacity_score=int(st.session_state.risk_capacity_score),
        risk_tolerance_score=int(st.session_state.risk_tolerance_score),
        auto_allocate_existing=bool(st.session_state.auto_allocate_existing),
        inflation_rate=float(st.session_state.inflation_rate_pct) / 100,
        return_adjustment=float(st.session_state.return_adjustment_pct) / 100,
        retirement_age=int(st.session_state.retirement_age),
        life_expectancy=int(st.session_state.life_expectancy),
        retirement_monthly_expenses=float(st.session_state.retirement_monthly_expenses),
        retirement_corpus=float(st.session_state.retirement_corpus),
        epf_balance=float(st.session_state.epf_balance),
        ppf_balance=float(st.session_state.ppf_balance),
        nps_balance=float(st.session_state.nps_balance),
    )


STEP_KEYS: dict[int, list[str]] = {
    0: ["age", "dependents"],
    1: ["monthly_income", "other_income", "monthly_expenses"],
    2: ["savings", "emergency_fund", "existing_investments", "investment_type", "auto_allocate_existing", "loans"],
    3: ["has_health_insurance", "life_cover_option", "life_insurance_coverage"],
    4: [
        "risk_capacity_score", "risk_tolerance_score", "tax_regime",
        "chosen_risk_profile", "effective_risk_profile",
        "inflation_rate_pct", "return_adjustment_pct",
        "retirement_age", "life_expectancy", "retirement_monthly_expenses", "retirement_corpus",
        "epf_balance", "ppf_balance", "nps_balance",
    ],
    5: ["goals"],
    6: ["plan"],
}


def goto(step_delta: int):
    st.session_state.current_step = min(max(0, st.session_state.current_step + step_delta), len(STEPS) - 1)
    st.rerun()


def reset_step(step_index: int):
    """Reset only the fields belonging to *step_index* back to their defaults."""
    defaults = _all_field_defaults()
    for key in STEP_KEYS.get(step_index, []):
        if key in defaults:
            st.session_state[key] = defaults[key]


def reset_all():
    """Clear the entire session state and restart at step 0."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def send_pdf_email(to_email: str, pdf_bytes: bytes, health_score: int, goals_count: int) -> bool:
    """Send the PDF report to the user's email via Resend."""
    api_key = st.secrets.get("RESEND_API_KEY", "")
    if not api_key:
        return False
    resend.api_key = api_key
    try:
        resend.Emails.send({
            "from": "Financial Planner <onboarding@resend.dev>",
            "to": [to_email],
            "subject": f"Your Financial Plan (Health Score: {health_score}/100)",
            "html": (
                f"<h2>Your Personal Financial Plan</h2>"
                f"<p>Hi,</p>"
                f"<p>Your financial plan is attached. Here's a quick snapshot:</p>"
                f"<ul>"
                f"<li><b>Health Score:</b> {health_score} / 100</li>"
                f"<li><b>Goals planned:</b> {goals_count}</li>"
                f"</ul>"
                f"<p>Open the attached PDF for your full plan with recommendations, "
                f"action items, and investment guidance.</p>"
                f"<hr>"
                f"<p style='font-size:12px;color:#888'>Generated by Personal Financial Planner. "
                f"This is not financial advice — consult a SEBI-registered investment adviser.</p>"
            ),
            "attachments": [{
                "filename": "Personal_Financial_Plan.pdf",
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
            }],
        })
        return True
    except Exception as e:
        import logging
        logging.warning(f"Email send failed: {e}")
        return False


def _sanitize_for_sheet(value: str) -> str:
    """Prevent CSV/formula injection in Google Sheets."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def record_email(email: str, health_score: int, goals_count: int):
    """Append a row to the Google Sheet with the email and plan metadata."""
    try:
        creds_dict = dict(st.secrets["gsheets"])
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(st.secrets["GSHEET_ID"]).sheet1
        from datetime import datetime
        sheet.append_row([
            _sanitize_for_sheet(email),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            health_score,
            goals_count,
        ])
    except Exception as e:
        import logging
        logging.warning(f"Email recording failed: {e}")


load_query_params_once()
ensure_defaults()

with st.sidebar:
    st.subheader("Planner Settings")
    theme = st.selectbox("Reading theme", ["System", "Light", "Dark", "Sepia"], key="reading_theme")
    font_size = st.selectbox("Text size", ["Comfortable", "Large", "Extra large"], key="text_size")
    st.divider()
    st.subheader("Steps")
    for i, step in enumerate(STEPS):
        marker = "✓" if i < st.session_state.current_step else "•"
        if i == st.session_state.current_step:
            marker = "→"
        if st.button(f"{marker} {i + 1}. {step}", key=f"nav_{i}", use_container_width=True):
            st.session_state.current_step = i
            st.rerun()
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Reset page", use_container_width=True, help="Reset this step's fields to defaults"):
            reset_step(st.session_state.current_step)
            st.toast(f"Step {st.session_state.current_step + 1} reset to defaults.")
            st.rerun()
    with col2:
        if st.button("Reset all", use_container_width=True, type="secondary", help="Clear everything and start over"):
            reset_all()
            st.rerun()

inject_css(theme, font_size)

st.title("Personal Financial Planner")
st.caption("A guided India-first money checkup for safety, goals, and next actions.")

step = st.session_state.current_step


if step == 0:
    st.header("1. About You")
    st.write("Let's place the plan in your household context first.")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.age = st.select_slider("Your age", options=list(range(18, 81)), value=int(st.session_state.age))
    with col2:
        st.session_state.dependents = st.selectbox("Number of dependents", options=list(range(7)), index=int(st.session_state.dependents))
    if st.button("Next: Money In & Out →", type="primary"):
        goto(1)


elif step == 1:
    st.header("2. Money In & Out")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.monthly_income = st.number_input("Monthly take-home salary (₹)", min_value=0.0, step=5000.0, value=float(st.session_state.monthly_income))
        st.session_state.other_income = st.number_input("Other monthly income (₹)", min_value=0.0, step=1000.0, value=float(st.session_state.other_income))
    with col2:
        st.session_state.monthly_expenses = st.number_input(
            "Monthly expenses before EMIs (₹)",
            min_value=0.0,
            step=5000.0,
            value=float(st.session_state.monthly_expenses),
            help="Rent, groceries, transport, school fees, subscriptions, and regular spending. Put loan EMIs in the next step.",
        )
    total_income = st.session_state.monthly_income + st.session_state.other_income
    surplus_before_emi = total_income - st.session_state.monthly_expenses
    col1, col2, col3 = st.columns(3)
    col1.metric("Total monthly income", inr(total_income))
    col2.metric("Before-EMI surplus", inr(surplus_before_emi))
    col3.metric("Annual income", inr(total_income * 12))
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            goto(-1)
    with col2:
        if st.button("Next: Assets & Loans →", type="primary"):
            goto(1)


elif step == 2:
    st.header("3. Assets & Loans")
    _inv_types = ["None", "Mutual Funds", "Stocks / ETFs", "Pension / PPF / EPF", "Property", "Bonds / FD", "Mixed"]
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.savings = st.number_input("Savings / liquid cash (₹)", min_value=0.0, step=10000.0, value=float(st.session_state.savings))
        st.session_state.emergency_fund = st.number_input("Emergency fund (₹)", min_value=0.0, step=10000.0, value=float(st.session_state.emergency_fund))
    with col2:
        st.session_state.existing_investments = st.number_input("Existing investments (₹)", min_value=0.0, step=10000.0, value=float(st.session_state.existing_investments))
        st.session_state.investment_type = st.selectbox(
            "Type of existing investments",
            _inv_types,
            index=_inv_types.index(st.session_state.investment_type) if st.session_state.investment_type in _inv_types else 0,
        )
        st.session_state.auto_allocate_existing = st.checkbox("Auto-apply unassigned investments to high-priority goals", value=bool(st.session_state.auto_allocate_existing))

    st.subheader("Loans & EMIs")
    st.caption("High-interest debt gets priority over discretionary investing.")
    for i, loan in enumerate(st.session_state.loans):
        with st.expander(f"Loan {i + 1}: {truncate(loan.get('name', 'Loan'))}", expanded=True):
            col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
            with col1:
                st.session_state.loans[i]["name"] = st.text_input("Loan name", value=loan.get("name", "Loan"), key=f"loan_name_{i}")
            with col2:
                st.session_state.loans[i]["balance"] = st.number_input("Outstanding (₹)", min_value=0.0, value=float(loan.get("balance", 0.0)), step=10000.0, key=f"loan_bal_{i}")
            with col3:
                _rate_pct = st.number_input("Interest % p.a.", min_value=0.0, value=float(loan.get("annual_rate", 0.12)) * 100, step=0.5, key=f"loan_rate_{i}")
                st.session_state.loans[i]["annual_rate"] = _rate_pct / 100
            with col4:
                st.session_state.loans[i]["monthly_emi"] = st.number_input("Monthly EMI (₹)", min_value=0.0, value=float(loan.get("monthly_emi", 0.0)), step=1000.0, key=f"loan_emi_{i}")
            if st.button("Remove loan", key=f"remove_loan_{i}"):
                st.session_state.loans.pop(i)
                st.rerun()
    if st.button("+ Add loan"):
        st.session_state.loans.append({"name": "Credit card / loan", "balance": 100000.0, "annual_rate": 0.18, "monthly_emi": 5000.0})
        st.rerun()

    profile_preview = build_profile()
    col1, col2, col3 = st.columns(3)
    col1.metric("Monthly EMIs", inr(total_monthly_emi(profile_preview)))
    col2.metric("Debt outstanding", inr(total_debt(profile_preview)))
    col3.metric("High-interest debt", inr(high_interest_debt(profile_preview)))
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back"):
            goto(-1)
    with col2:
        if st.button("Next: Safety Net", type="primary"):
            goto(1)


elif step == 3:
    st.header("4. Safety Net")
    st.write("Insurance and emergency cash protect the plan before investment returns matter.")
    total_income = st.session_state.monthly_income + st.session_state.other_income
    recommended_coverage = total_income * 120
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.has_health_insurance = st.radio(
            "Health insurance?", ["Yes", "No"], horizontal=True,
            index=["Yes", "No"].index(st.session_state.has_health_insurance),
        )
        if st.session_state.has_health_insurance == "No":
            st.caption("Start with at least ₹15L individual / ₹25L family floater for metros. ₹10L minimum for smaller cities.")
    with col2:
        st.session_state.life_cover_option = st.radio(
            "Life insurance (term plan)?", ["Yes", "No"], horizontal=True,
            index=["Yes", "No"].index(st.session_state.life_cover_option),
        )
        if st.session_state.life_cover_option == "Yes":
            st.session_state.life_insurance_coverage = st.number_input(
                "Sum assured (₹)",
                min_value=0.0,
                value=float(st.session_state.life_insurance_coverage or recommended_coverage),
                step=500000.0,
                help=f"Benchmark: {inr(recommended_coverage)} (10x annual income)",
            )
        elif st.session_state.dependents > 0:
            st.caption(f"With dependents, benchmark cover is {inr(recommended_coverage)}.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back"):
            goto(-1)
    with col2:
        if st.button("Next: Risk & Assumptions", type="primary"):
            goto(1)


elif step == 4:
    st.header("5. Risk & Assumptions")
    age_suggestion = suggested_risk_profile(st.session_state.age)
    st.info(f"Age-based starting point: **{age_suggestion.capitalize()}** — {AGE_RISK_NOTES[age_suggestion]}")

    col1, col2 = st.columns(2)
    with col1:
        st.session_state.risk_capacity_score = st.selectbox(
            "Income stability and debt capacity",
            options=[0, 1, 2, 3],
            format_func=lambda x: ["Fragile", "Cautious", "Comfortable", "Very strong"][x],
            index=int(st.session_state.risk_capacity_score),
        )
        st.session_state.risk_tolerance_score = st.selectbox(
            "Reaction to a 30% portfolio fall",
            options=[0, 1, 2, 3],
            format_func=lambda x: ["Sell quickly", "Lose sleep", "Stay invested", "Invest more"][x],
            index=int(st.session_state.risk_tolerance_score),
        )
    with col2:
        st.session_state.tax_regime = st.selectbox("Tax regime", ["New", "Old"], index=["New", "Old"].index(st.session_state.tax_regime))
        manual_risk = st.radio(
            "Preferred risk profile",
            ["Conservative", "Moderate", "Aggressive"],
            index=["Conservative", "Moderate", "Aggressive"].index(st.session_state.chosen_risk_profile),
            horizontal=True,
        )
        st.session_state.chosen_risk_profile = manual_risk

    capacity_profile = risk_profile_from_score(st.session_state.risk_capacity_score)
    tolerance_profile = risk_profile_from_score(st.session_state.risk_tolerance_score)
    effective = stricter_risk_profile(age_suggestion, capacity_profile, tolerance_profile, manual_risk.lower())
    st.session_state.effective_risk_profile = effective
    st.success(f"Planner will use: {effective.capitalize()} risk profile")

    with st.expander("Advanced assumptions"):
        st.session_state.inflation_rate_pct = st.number_input("Inflation assumption (% p.a.)", min_value=0.0, max_value=12.0, step=0.1, value=float(st.session_state.inflation_rate_pct))
        st.session_state.return_adjustment_pct = st.number_input("Return adjustment (% p.a.)", min_value=-5.0, max_value=5.0, step=0.25, value=float(st.session_state.return_adjustment_pct))
        st.caption(f"Assumptions last reviewed: {LAST_UPDATED}; effective from {DATA_EFFECTIVE_FROM}.")
        st.markdown("**Selected return assumptions:**")
        st.write(
            {
                "Nifty 50 index": pct(RETURN_ASSUMPTIONS["equity_largecap_index"]),
                "PPF": pct(RETURN_ASSUMPTIONS["debt_ppf"]),
                "Liquid fund": pct(RETURN_ASSUMPTIONS["debt_liquid"]),
                "Gold ETF": pct(RETURN_ASSUMPTIONS["gold_etf"]),
            }
        )
        for source in DATA_SOURCES:
            st.caption(source)
        st.caption(f"Tax note: {TAX_NOTES['equity_ltcg']}")

    with st.expander("Retirement planning inputs"):
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.retirement_age = st.number_input("Retirement age", min_value=45, max_value=75, value=int(st.session_state.retirement_age))
            st.session_state.life_expectancy = st.number_input(
                "Life expectancy", min_value=65, max_value=100, value=int(st.session_state.life_expectancy),
                help="India's average is ~70, but for financial planning you should plan for living longer. 85 covers the 90th percentile — running out of money is worse than having extra.",
            )
        with col2:
            # Pre-populate retirement expenses from current expenses + inflation if not yet set
            if st.session_state.retirement_monthly_expenses == 0.0:
                _years_to_ret = max(0, int(st.session_state.retirement_age) - int(st.session_state.age))
                _infl = float(st.session_state.inflation_rate_pct) / 100
                _auto = float(st.session_state.monthly_expenses) * (1 + _infl) ** _years_to_ret
                st.session_state.retirement_monthly_expenses = round(_auto / 1000) * 1000
            _ytr = max(0, int(st.session_state.retirement_age) - int(st.session_state.age))
            _infl_pct = float(st.session_state.inflation_rate_pct)
            st.session_state.retirement_monthly_expenses = st.number_input(
                "Monthly retirement expenses (today's ₹)",
                min_value=0.0,
                step=5000.0,
                value=float(st.session_state.retirement_monthly_expenses),
                help=f"Pre-filled from your current monthly expenses inflated at {_infl_pct:.1f}% p.a. for {_ytr} years. Adjust if your retirement lifestyle will differ."
            )
            st.session_state.retirement_corpus = st.number_input("Other retirement corpus (₹)", min_value=0.0, step=50000.0, value=float(st.session_state.retirement_corpus), help="Investments already earmarked for retirement (excluding EPF/PPF/NPS below).")
        st.markdown("**Existing retirement balances**")
        st.caption("These reduce the monthly SIP needed for retirement.")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.session_state.epf_balance = st.number_input("EPF balance (₹)", min_value=0.0, step=50000.0, value=float(st.session_state.epf_balance), help="Check your EPFO passbook or recent payslip.")
        with col2:
            st.session_state.ppf_balance = st.number_input("PPF balance (₹)", min_value=0.0, step=50000.0, value=float(st.session_state.ppf_balance))
        with col3:
            st.session_state.nps_balance = st.number_input("NPS balance (₹)", min_value=0.0, step=50000.0, value=float(st.session_state.nps_balance))

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back"):
            goto(-1)
    with col2:
        if st.button("Next: Goals", type="primary"):
            goto(1)


elif step == 5:
    st.header("6. Goals")
    st.caption("Quick-add targets are treated as today's cost and inflated automatically.")
    added_names = {g["name"] for g in st.session_state.goals}
    cols = st.columns(2)
    for i, sg in enumerate(SUGGESTED_GOALS):
        already_added = sg["name"] in added_names
        with cols[i % 2]:
            if st.button(
                f"{'✓' if already_added else '+'} {sg['name']} — {inr(sg['target'])} in {sg['years']} yr",
                key=f"sg_{i}",
                disabled=already_added,
                use_container_width=True,
            ):
                st.session_state.goals.append({
                    "name": sg["name"],
                    "target": float(sg["target"]),
                    "years": sg["years"],
                    "priority": sg["priority"],
                    "target_is_today_value": True,
                    "existing_allocated": 0.0,
                })
                st.session_state.last_added = len(st.session_state.goals) - 1
                st.rerun()

    if not st.session_state.goals:
        st.caption("No goals yet. Add one to generate a plan.")

    for i, goal in enumerate(st.session_state.goals):
        title = f"Goal {i + 1}: {truncate(goal['name'])} - {inr(goal['target'])} in {goal['years']} yrs"
        with st.expander(title, expanded=i == st.session_state.last_added):
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            with col1:
                st.session_state.goals[i]["name"] = st.text_input("Goal name", value=goal["name"], key=f"name_{i}")
            with col2:
                st.session_state.goals[i]["target"] = st.number_input("Target amount (₹)", min_value=0.0, value=float(goal["target"]), step=10000.0, key=f"target_{i}")
            with col3:
                st.session_state.goals[i]["years"] = st.number_input("Years", min_value=1, max_value=50, value=int(goal["years"]), key=f"years_{i}")
            with col4:
                st.session_state.goals[i]["priority"] = st.selectbox("Priority", ["High", "Medium", "Low"], index=["High", "Medium", "Low"].index(goal["priority"]), key=f"priority_{i}")
            col1, col2 = st.columns(2)
            with col1:
                st.session_state.goals[i]["target_is_today_value"] = st.checkbox(
                    "Target is today's value; inflate it",
                    value=bool(goal.get("target_is_today_value", True)),
                    key=f"infl_{i}",
                )
            with col2:
                st.session_state.goals[i]["existing_allocated"] = st.number_input(
                    "Existing investments allocated (₹)",
                    min_value=0.0,
                    value=float(goal.get("existing_allocated", 0.0)),
                    step=10000.0,
                    key=f"existing_goal_{i}",
                )
            if st.session_state.confirm_remove_goal == i:
                st.warning("Remove this goal?")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, remove", key=f"remove_yes_{i}"):
                        st.session_state.goals.pop(i)
                        st.session_state.confirm_remove_goal = None
                        st.session_state.last_added = -1
                        st.toast("Goal removed.")
                        st.rerun()
                with col2:
                    if st.button("Keep goal", key=f"remove_no_{i}"):
                        st.session_state.confirm_remove_goal = None
                        st.rerun()
            elif st.button("Remove goal", key=f"remove_{i}"):
                st.session_state.confirm_remove_goal = i
                st.rerun()

    if st.button("+ Add custom goal"):
        st.session_state.goals.append({
            "name": "My Goal",
            "target": 500000.0,
            "years": 5,
            "priority": "Medium",
            "target_is_today_value": True,
            "existing_allocated": 0.0,
        })
        st.session_state.last_added = len(st.session_state.goals) - 1
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back"):
            goto(-1)
    with col2:
        if st.button("Next: Your Plan", type="primary"):
            goto(1)


elif step == 6:
    st.header("7. Your Plan")
    generate_label = "Regenerate Plan" if st.session_state.plan else "Generate My Financial Plan"
    generate = st.button(generate_label, type="primary", use_container_width=True)
    if generate:
        if st.session_state.monthly_income <= 0:
            st.error("Enter your monthly take-home salary. It must be above ₹0.")
        elif st.session_state.monthly_expenses <= 0:
            st.error("Enter your monthly expenses before EMIs. It must be above ₹0.")
        elif not st.session_state.goals:
            st.error("Add at least one financial goal before generating the plan.")
        elif int(st.session_state.retirement_age) <= int(st.session_state.age):
            st.error(f"Retirement age ({int(st.session_state.retirement_age)}) must be greater than your current age ({int(st.session_state.age)}).")
        elif int(st.session_state.life_expectancy) <= int(st.session_state.retirement_age):
            st.error(f"Life expectancy ({int(st.session_state.life_expectancy)}) must be greater than retirement age ({int(st.session_state.retirement_age)}).")
        else:
            with st.spinner("Building your financial plan…"):
                st.session_state.pdf_bytes = None  # clear cached PDF
                profile = build_profile()
                recs = goal_recommendations(profile)
                health = compute_health_score(profile, recs)
                gaps = gap_analysis(profile)
                actions = action_plan(profile, recs, gaps)
                playbook = personal_finance_playbook(profile, health, recs, gaps)
                st.session_state.plan = {
                    "profile": profile,
                    "recs": recs,
                    "health": health,
                    "gaps": gaps,
                    "actions": actions,
                    "playbook": playbook,
                }
                sync_query_params()
                st.toast("Plan generated and URL state updated.")

    if st.session_state.plan:
        plan = st.session_state.plan
        profile = plan["profile"]
        recs = plan["recs"]
        health = plan["health"]
        gaps = plan["gaps"]
        actions = plan["actions"]
        playbook = plan.get("playbook") or personal_finance_playbook(profile, health, recs, gaps)
        surplus = monthly_surplus(profile)
        needed = total_monthly_needed(recs)

        st.subheader("Snapshot")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Surplus after EMIs", inr(surplus))
        col2.metric("Monthly SIP needed", inr(needed))
        col3.metric("Left after goals", inr(max(0, surplus - needed)), delta=None if surplus >= needed else f"{inr(needed - surplus)} shortfall", delta_color="inverse")
        col4.metric("Job-loss buffer", f"{job_loss_buffer_months(profile):.1f} mo")

        total_score = health["total"]
        label = score_label(total_score)
        score_var = "var(--pfp-good)" if total_score >= 70 else "var(--pfp-warn)" if total_score >= 45 else "var(--pfp-bad)"
        st.subheader("Financial Health Score")
        col1, col2 = st.columns([1, 3])
        with col1:
            st.markdown(
                f"<div class='pfp-score' style='color:{score_var}'><div class='pfp-score-num'>{total_score}</div>"
                f"<div class='pfp-score-sub'>out of 100</div><strong>{label}</strong></div>",
                unsafe_allow_html=True,
            )
        with col2:
            cats = {
                "Emergency Fund": ("emergency_fund", 20),
                "Savings Rate": ("savings_rate", 20),
                "Health Insurance": ("health_insurance", 15),
                "Life Insurance": ("life_insurance", 15),
                "Goal Feasibility": ("goal_feasibility", 30),
            }
            for label_text, (key, max_v) in cats.items():
                s = health["scores"][key]
                bar_pct = int(s / max_v * 100)
                bar_var = "var(--pfp-good)" if bar_pct >= 70 else "var(--pfp-warn)" if bar_pct >= 40 else "var(--pfp-bad)"
                st.markdown(
                    f"<div style='margin-bottom:8px'><div style='display:flex;justify-content:space-between;font-size:12px'>"
                    f"<span>{label_text}</span><span style='color:{bar_var};font-weight:600'>{s}/{max_v}</span></div>"
                    f"<div class='pfp-bar-track'><div class='pfp-bar-fill' style='background:{bar_var};width:{bar_pct}%'></div></div></div>",
                    unsafe_allow_html=True,
                )
        with st.expander("What drives your score?"):
            for label_text, (key, _) in cats.items():
                st.markdown(f"**{label_text}:** {health['details'][key]}")

        st.subheader("Personal Finance Playbook")
        personality = playbook["personality"]
        st.info(f"**{personality['label']}** - {personality['summary']} {playbook['one_sentence']}")
        with st.expander("Your money questions, answered", expanded=True):
            for answer in playbook["answers"]:
                st.markdown(f"- {answer}")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Tax-smart notes**")
            for note in playbook["tax_notes"]:
                st.markdown(f"- {note}")
        with col2:
            st.markdown("**Avoid for now**")
            for item in playbook["avoid"]:
                st.markdown(f"- {item}")

        debt = playbook["debt_strategy"]
        with st.expander("Debt strategy"):
            st.write(debt["summary"])
            for item in debt["items"]:
                st.markdown(f"- {item}")

        st.subheader("30 / 60 / 90 Day Action Plan")
        for block in actions:
            with st.expander(block["period"], expanded=block["period"] == "Next 30 days"):
                for item in block["items"]:
                    st.markdown(f"- {item}")

        if gaps:
            st.subheader("Action Items")
            for gap in gaps:
                st.warning(gap)

        st.subheader(f"Goal Recommendations ({len(recs)} goals)")
        for rec in recs:
            alloc = rec["allocation"]
            split = rec["asset_sip_split"]
            tag = "<span class='tag-good'>Feasible</span>" if rec["feasible"] else "<span class='tag-warn'>Stretch</span>"
            st.markdown(
                f"<div class='pfp-card'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                f"<span style='font-size:16px;font-weight:700'>{truncate(rec['name'])} — {rec['priority'].capitalize()}</span>"
                f"{tag}</div>"
                f"<div style='font-size:13px;color:var(--pfp-muted);margin-top:4px'>"
                f"{inr(rec['monthly_needed'])}/mo for {rec['years']} years → {inr(rec['future_target'])}"
                f" (today: {inr(rec['today_target'])})</div>"
                f"{alloc_bar(alloc['equity'], alloc['debt'], alloc['gold'], alloc['cash'])}"
                f"</div>",
                unsafe_allow_html=True,
            )
            with st.expander("Details"):
                col1, col2, col3 = st.columns(3)
                col1.metric("Monthly SIP", inr(rec["monthly_needed"]))
                col2.metric("Expected return", pct(rec["return"]))
                col3.metric("Existing applied", inr(rec["existing_applied"]))
                st.caption(alloc["rationale"])

                st.markdown("**Monthly SIP split**")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Equity", inr(split["equity"]))
                c2.metric("Debt", inr(split["debt"]))
                c3.metric("Gold", inr(split["gold"]))
                c4.metric("Cash / Liquid", inr(split["cash"]))

                guidance = rec.get("fund_category_guidance", {})
                if guidance:
                    st.markdown("**Fund category guidance**")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.caption("Suitable")
                        for item in guidance.get("suitable", []):
                            st.markdown(f"- {item}")
                    with col2:
                        st.caption("Use caution")
                        for item in guidance.get("use_caution", []):
                            st.markdown(f"- {item}")
                    with col3:
                        st.caption("Avoid")
                        for item in guidance.get("avoid", []):
                            st.markdown(f"- {item}")

                st.markdown("**Scenario outcomes at the same SIP**")
                c1, c2, c3 = st.columns(3)
                c1.metric("Conservative", inr(rec["scenarios"]["conservative"]))
                c2.metric("Base", inr(rec["scenarios"]["base"]))
                c3.metric("Optimistic", inr(rec["scenarios"]["optimistic"]))

                if not rec["feasible"]:
                    trade = rec["tradeoffs"]
                    st.markdown("**Trade-offs**")
                    risk_note = ""
                    if trade["higher_risk_profile_sip"] < rec["monthly_needed"]:
                        risk_note = f" Move to next risk profile: {inr(trade['higher_risk_profile_sip'])}/mo."
                    st.info(
                        f"Extend by 2 years: {inr(trade['extend_by_2_years'])}/mo. "
                        f"Reduce target by 10%: {inr(trade['reduce_target_10pct'])}/mo. "
                        f"Extra monthly capacity needed: {inr(trade['increase_needed'])}."
                        f"{risk_note}"
                    )

                if alloc["equity"] > 0:
                    st.markdown("**Equity**")
                    for inst in alloc["equity_instruments"]:
                        st.markdown(f"- {inst}")
                st.markdown("**Debt**")
                for inst in alloc["debt_instruments"]:
                    if profile.tax_regime == "new" and ("80C" in inst or "80CCD" in inst):
                        st.markdown(f"- {inst} Tax deduction may not apply under your selected regime.")
                    else:
                        st.markdown(f"- {inst}")
                if alloc["gold"] > 0:
                    st.markdown("**Gold**")
                    for inst in alloc["gold_instruments"]:
                        st.markdown(f"- {inst}")
                if alloc["cash"] > 0:
                    st.markdown("**Cash / Liquid**")
                    for inst in alloc["cash_instruments"][:2]:
                        st.markdown(f"- {inst}")

        st.subheader("Retirement Check")
        ret = retirement_summary(profile)
        col1, col2, col3 = st.columns(3)
        col1.metric("Years to retirement", ret["years_to_retirement"])
        col2.metric("Corpus estimate", inr(ret["corpus_needed"]))
        col3.metric("Retirement SIP", f"{inr(ret['monthly_needed'])}/mo")
        st.caption(
            f"Corpus accounts for inflation-adjusted withdrawals over {ret['retirement_years']} years, "
            f"assuming the corpus earns {ret['withdrawal_return']:.0%} p.a. (conservative, debt-heavy mix) during retirement."
        )

        with st.expander("Assumptions & guardrails"):
            st.write(f"Assumptions last reviewed: {LAST_UPDATED}; effective from {DATA_EFFECTIVE_FROM}.")
            st.write(f"Inflation: {pct(profile.inflation_rate)} p.a.; return adjustment: {profile.return_adjustment * 100:+.1f}% p.a.")
            st.write(TAX_NOTES["equity_ltcg"])
            st.write(TAX_NOTES["debt_mf"])
            st.warning(
                "This app does not know your full tax status, liabilities, employer benefits, health conditions, "
                "existing asset allocation, or legal obligations. Consult a SEBI-registered investment adviser before making investment decisions."
            )
            for source in DATA_SOURCES:
                st.caption(source)

        if "pdf_bytes" not in st.session_state or not st.session_state.pdf_bytes:
            with st.spinner("Preparing PDF…"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp_path = tmp.name
                generate_pdf(profile, health, recs, gaps, tmp_path, actions, playbook)
                with open(tmp_path, "rb") as f:
                    st.session_state.pdf_bytes = f.read()
                os.unlink(tmp_path)
        pdf_bytes = st.session_state.pdf_bytes

        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name="Personal_Financial_Plan.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )

        st.markdown("**Email your report**")
        col1, col2 = st.columns([3, 1])
        with col1:
            email_addr = st.text_input("Email address", placeholder="you@example.com", label_visibility="collapsed")
        with col2:
            send_clicked = st.button("Send PDF", use_container_width=True)
        if send_clicked:
            if not email_addr or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_addr):
                st.error("Enter a valid email address.")
            else:
                with st.spinner("Sending…"):
                    ok = send_pdf_email(email_addr, pdf_bytes, health["total"], len(recs))
                if ok:
                    record_email(email_addr, health["total"], len(recs))
                    st.success(f"Report sent to {email_addr}")
                else:
                    st.error("Could not send email. Check your Resend API key in secrets.")

        st.caption("Your current URL now contains a resumable snapshot of the inputs.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back to Goals"):
            goto(-1)
    with col2:
        if st.button("Update share/resume URL"):
            sync_query_params()
            st.toast("URL updated.")
