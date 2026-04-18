# Projects Deploy

Live Streamlit apps deployed via [Streamlit Community Cloud](https://streamlit.io/cloud).

## Apps

### Personal Financial Planner

A guided, India-specific financial planning tool that generates a personalised health score, per-goal investment recommendations, a 30/60/90-day action plan, and a downloadable PDF report.

**Features**

- Seven-step guided flow covering income, expenses, assets, loans, insurance, risk profiling, and goals
- India-first instrument recommendations (Nifty 50 index funds, PPF, SGBs, NPS, ELSS, etc.)
- Financial health score (0-100) with transparent breakdown
- Per-goal asset allocation with monthly SIP splits across equity, debt, gold, and cash
- Conservative / base / optimistic scenario outcomes
- Job-loss buffer and retirement planning
- Downloadable PDF report via ReportLab

**Tech stack:** Python, Streamlit, ReportLab. No external APIs -- all logic is self-contained.

**Run locally:**

```bash
cd financial-planner
pip install -r requirements.txt
streamlit run app.py
```

## Disclaimer

The tools in this repo are for educational and informational purposes only. They do not constitute financial advice. Consult a SEBI-registered investment adviser before making investment decisions.

## License

MIT
