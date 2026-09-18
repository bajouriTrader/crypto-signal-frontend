SignalDesk V.2.10.80 — Watchlist Observer (observation-only)
============================================================
Backend deploy (HF Space):
  - version.py
  - watchlist.py
  - watchlist_observer.py  (NEW)

Frontend (GitHub Pages):
  - src/AutoSignalList.jsx

What changes:
  - Each /watchlist-signals row gets:
      tradeability, tradeability_reasons, observer{}
  - UI shows Score (not "96%") + Trade
  - Explicit: Score ≠ win probability
  - NO entry gate / threshold changes
  - Snapshot ring in memory for future calibration

Does NOT change:
  - real_trade open filters
  - min_confluence / min_rr / anti-chase
