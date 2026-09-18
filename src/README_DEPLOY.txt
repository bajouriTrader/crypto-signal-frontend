SignalDesk V.2.10.79 — compact entry gate chips
==============================================
Backend: entry_block_summary on /real-trade/status
  chips[]: {ok, id, t}  + line + can_enter

Frontend: RealTradePanel shows compact ✓/✗ chips
  (pause / news / slots / recent reject reasons)
  ADX exception line only when pause is BTC-related (not global SL lock)

Deploy:
  HF: real_trade.py + version.py
  GitHub Pages: src/RealTradePanel.jsx (replace)
