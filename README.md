# FROZEN FORECAST — Streamlit MVP

Standalone NHL goal-total projection dashboard adapted from the uploaded **NHL Score Predictor and Dashboard.ipynb**, especially the corrected team-stat refresh (Cell 38B), goalie adjustment (Cell 39), Daily Faceoff parser (Cells 41–43), live goal projection formula (Cell 47), and roster/reliability checks (Cells 54–55).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Or deploy `app.py` as the main file in a Streamlit Community Cloud repository containing `engine.py`, `requirements.txt`, and `assets/`.

## What works

- Independent dashboard page, dynamic Eastern Time date and refresh time
- NHL team/goalie statistics, Daily Faceoff goalie statuses, NHL roster verification
- Original baseline projection formula, three-column dark/ice-blue dashboard, team logos
- Reliability levels and CSV export; refresh cache of 10 minutes
- No projections after official puck drop; incomplete games skipped, not silently imputed

## Production limitations to resolve before treating this as a complete replacement

- **No durable historical storage yet.** The Colab notebook's Google Drive mount does not work on hosted Streamlit. This MVP does not write to the user's historical CSV files or train the adaptive ensemble. Connect a persistent database or secured cloud storage before production use.
- Daily Faceoff's embedded website data may change or be unavailable; the app fails visibly instead of fabricating goalie data.
- Live NHL statistics can include games played after a selected historical date. The date selector is intended for **current/upcoming** projections, not historical backtesting.
- Original experimental recent-form models (`v2_recent5_w20`, `v2_recent10_w20`) are not silently represented as active. The live dashboard uses the notebook's **v1 goalie-adjusted baseline**.
- Not yet tested against live external APIs in this offline packaging environment; verify in deployed environment.
- User should not commit personal Google Drive exports or secrets to a public repository.

## Next production milestone

Connect a secure durable history store; port the existing pregame snapshots, result collection, and chronological training/validation functions; then test with fresh games. This is a working *dashboard starter*, not a claim of a validated self-learning model.
