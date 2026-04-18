# Changelog — Personal Financial Planner

## v2.0 — 2026-04-18

### New features
- Personal Finance Playbook: personality archetype (Stabiliser / Debt Breaker / Foundation Builder / Goal Stretcher / Wealth Accelerator / Steady Builder), one-sentence next action, practical money Q&A, tax-smart notes, debt strategy, and "avoid for now" list
- Per-goal fund category guidance: suitable fund categories, caution areas, and categories to avoid based on horizon, allocation, risk profile, and tax regime
- Guided seven-step wizard with sidebar step indicator replacing the single long form
- URL state sync via `st.query_params` for share/resume
- Loan tracking: balance, interest rate, and EMI per loan; high-interest debt surfaces in scoring and action items
- Existing investments can be mapped per goal or auto-applied to high-priority goals
- Goal targets can be toggled as today's value and inflated to a future target
- Conservative/base/optimistic scenario outcomes per goal
- Stretch goal trade-offs: extend by 2 years, reduce target 10%, or find extra monthly capacity
- 30/60/90-day action plan in UI and PDF
- Job-loss buffer metric
- Risk profile now combines age, capacity, tolerance, and user preference; uses the strictest result
- Tax regime (new/old) awareness throughout recommendations and guardrails
- Retirement inputs: retirement age, life expectancy, monthly retirement expenses, current retirement corpus
- Reading theme (System / Light / Dark / Sepia) and text-size controls that persist in session state
- Assumptions transparency panel: last reviewed date, data sources, inflation and return settings

### PDF
- Extended with Playbook, debt strategy, avoid list, and fund category guidance per goal

### Deployment
- Moved to `financial-planner/` subfolder in `apsathe123/projects_deploy`; deploy via `financial-planner/app.py`

## v1.0 — 2026-04-18

### Initial release
- Streamlit web app for India-specific personal financial planning
- Financial health score (0–100) across 5 components: emergency fund, savings rate, health insurance, life insurance, goal feasibility
- Per-goal investment recommendations with equity/debt/gold/cash allocation
- India-specific instruments: Nifty 50 index funds, PPF, NPS Tier-1, ELSS, SGB, liquid funds
- 12 allocation profiles (4 horizon bands × 3 risk profiles)
- Suggested goals quick-add: Wedding, Car, House Down Payment, Kids Education, Emergency Corpus, Retirement, Travel, Gadget/Bike
- Life insurance scoring: graded against 10× annual income benchmark; savings treated as self-insurance for 0-dependent users
- Other income field added to income section
- Dependents dropdown (0–6)
- Indian number formatting (₹ Cr / L notation) in UI; `Rs.` in PDF (ReportLab font limitation)
- Downloadable PDF report via ReportLab
- Deployed to Streamlit Community Cloud via `apsathe123/projects_deploy`
