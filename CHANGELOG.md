# Changelog — Personal Financial Planner

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
