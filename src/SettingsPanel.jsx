import { useEffect, useState } from 'react'
import { authFetch } from './auth'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

/** English labels only — key names match runtime_settings / real_trade */
const LABELS = {
  // Main control
  enable_new_entries: 'enable_new_entries — Allow new real entries',
  auto_pause_entries_on_btc_regime: 'auto_pause_entries_on_btc_regime — Pause on BTC WEAK/CHOP',
  auto_resume_min_btc_conf: 'auto_resume_min_btc_conf — Min BTC conf to resume',
  auto_pause_on_btc_bear_stack: 'auto_pause_on_btc_bear_stack — Pause when BTC stack is bear',

  // Real entry
  min_confluence: 'min_confluence — Min real confluence score',
  min_sl_distance_pct: 'min_sl_distance_pct — Min SL distance %',
  max_sl_distance_pct: 'max_sl_distance_pct — Max SL distance %',
  min_rr: 'min_rr — Min net R:R (after fees)',
  round_trip_friction_pct: 'round_trip_friction_pct — Fee+slippage friction %',
  min_tp_distance_pct: 'min_tp_distance_pct — Min TP distance %',
  real_min_symbol_wr: 'real_min_symbol_wr — Min demo symbol WR %',
  symbol_cooldown_sec: 'symbol_cooldown_sec — Cooldown after reject (sec)',
  post_close_cooldown_sec: 'post_close_cooldown_sec — Cooldown after close (sec)',
  post_sl_cooldown_sec: 'post_sl_cooldown_sec — Cooldown after SL (sec)',
  post_negative_cooldown_sec: 'post_negative_cooldown_sec — Cooldown after negative close (sec)',
  negative_pnl_threshold_usdt: 'negative_pnl_threshold_usdt — PnL ≤ this = negative close (USDT)',
  symbol_sl_lock_count: 'symbol_sl_lock_count — SL count to lock symbol',
  symbol_sl_lock_lookback_sec: 'symbol_sl_lock_lookback_sec — Symbol lock lookback (sec)',
  symbol_sl_lock_sec: 'symbol_sl_lock_sec — Symbol lock duration (sec)',
  enable_btc_chop_gate: 'enable_btc_chop_gate — BTC CHOP gate for alts',
  btc_chop_block_alts: 'btc_chop_block_alts — Block alts when BTC=CHOP',
  btc_weak_min_conf: 'btc_weak_min_conf — Min BTC conf when WEAK (alts)',
  enable_chop_filter: 'enable_chop_filter — Chop market filter (legacy ADX)',
  chop_adx_threshold: 'chop_adx_threshold — Chop ADX threshold (NOT entry gate)',

  // ADX entry gate
  enable_min_adx_entry: 'enable_min_adx_entry — Enable min ADX entry gate',
  min_adx_1h_for_entry: 'min_adx_1h_for_entry — Min symbol ADX 1h to open',
  min_btc_adx_1h_for_alt: 'min_btc_adx_1h_for_alt — Min BTC ADX when opening alts',
  adx_strong_bypass_btc: 'adx_strong_bypass_btc — Symbol ADX ≥ this bypasses BTC pause',
  enable_strong_adx_bypass_btc_pause: 'enable_strong_adx_bypass_btc_pause — Allow strong-ADX BTC bypass',
  enable_adx_bypass_btc_chop: 'enable_adx_bypass_btc_chop — Allow ADX bypass when BTC=CHOP (keep OFF in .92+)',

  // V.2.10.97 — Range scalp (CHOP/WEAK multi-strategy path)
  enable_range_scalp: 'enable_range_scalp — Independent range_scalp engine in CHOP/WEAK',
  range_min_confluence: 'range_min_confluence — Min score for range_scalp (not the trend score)',
  range_max_sl_distance_pct: 'range_max_sl_distance_pct — Max structural SL % (not moved to fit)',
  range_min_rr: 'range_min_rr — Min net R:R for range (0.80; 1.05 blocks midpoint targets)',
  range_min_tp_pct: 'range_min_tp_pct — Min TP % to range midpoint',
  range_size_mult: 'range_size_mult — Size multiplier before the loss-budget bump',
  range_max_open_positions: 'range_max_open_positions — Range slots only (trend positions do not count)',
  range_ci_hard_max: 'range_ci_hard_max — CI ≥ this = unstructured noise (no entry)',
  range_er_floor: 'range_er_floor — Min ER on range path',
  range_allow_btc_weak: 'range_allow_btc_weak — Permit range when BTC=WEAK',
  range_allow_btc_chop: 'range_allow_btc_chop — Permit range when BTC=CHOP',
  range_signal_only: 'range_signal_only — ON = show range signals, do not send orders',
  range_time_stop_sec: 'range_time_stop_sec — Close range trades after this many seconds (5400 = 90m)',
  range_win_cooldown_sec: 'range_win_cooldown_sec — Cooldown after a winning range exit',
  range_max_loss_usdt: 'range_max_loss_usdt — Max estimated loss after rounding up to min notional',
  // V.2.11.8 — range exits (decided on exit_whatif n=20)
  range_fail_exit: 'range_fail_exit — Range: close a failed entry early (after N sec, almost no profit, price ≥ X·R against)',
  range_fail_exit_min_sec: 'range_fail_exit_min_sec — Seconds after entry before the failed-entry check (600 = 10 min)',
  range_fail_exit_mfe_max_pct: 'range_fail_exit_mfe_max_pct — Max favorable move % still counted as "never worked" (0.15)',
  range_fail_exit_adverse_r: 'range_fail_exit_adverse_r — Adverse move (in R) that triggers the exit (0.3)',
  range_profit_lock: 'range_profit_lock — Range: 72% profit lock / float exit (OFF = let range trades reach the exchange TP at the midline)',
  range_small_tp_auto: 'range_small_tp_auto — Range "take small profit" (+0.40% / +0.50%) switches ON automatically only when the 1m-path data shows it beats current rules; OFF = never',
  range_small_tp_min_n: 'range_small_tp_min_n — Minimum range trades with 1m paths before auto-enable',
  range_small_tp_min_delta_pp: 'range_small_tp_min_delta_pp — Required total advantage vs current rules (percentage points)',
  // V.2.11.6 — same-direction underwater guard
  underwater_block_same_dir: 'underwater_block_same_dir — Block a new same-direction entry while an open same-direction position is in loss',
  underwater_min_loss_pct: 'underwater_min_loss_pct — Loss % of the open position that counts as underwater (0.05 = old fixed value)',
  underwater_min_loss_usdt: 'underwater_min_loss_usdt — Loss $ of the open position that counts as underwater (0.02 = old fixed value)',
  paper_track_underwater_rejects: 'paper_track_underwater_rejects — Paper-track signals rejected ONLY by this guard (all other gates passed)',
  // V.2.11.3 — protected entry (limit IOC with slippage cap)
  entry_protected_ioc: 'entry_protected_ioc — Entry as LIMIT+IOC capped at max slippage (unfilled = no trade, no fee). Turn on only after the self-test passes',
  entry_max_slippage_pct: 'entry_max_slippage_pct — Max entry slippage % (auto-shrunk so any fill also passes the post-fill guard)',
  entry_protected_ioc_selftest: 'entry_protected_ioc_selftest — Once per restart: place a far-from-market IOC test order (cannot fill) to verify exchange accepts it; see protected_entry in status',
  // V.2.11.0 — BTC drift alignment
  btc_drift_guard_range: 'btc_drift_guard_range — Do not open range trades against a confirmed BTC drift (tracked as paper trades instead)',
  btc_drift_min_ret_pct: 'btc_drift_min_ret_pct — BTC move over the window (%) that, with the 1h EMA stack, confirms a drift',
  btc_drift_window_min: 'btc_drift_window_min — Drift window in minutes (closed 15m candles)',
  btc_drift_trend_follow: 'btc_drift_trend_follow — During BTC pause, allow trend signals in the drift direction (weak_trend size)',
  btc_drift_follow_min_symbol_conf: 'btc_drift_follow_min_symbol_conf — Min confidence when the symbol label is WEAK (TREND always ok)',
  btc_drift_same_dir_cap: 'btc_drift_same_dir_cap — Same-direction cap for the drift-aligned side (normal cap 1 when BTC is weak)',
  btc_drift_strong_ret_pct: 'btc_drift_strong_ret_pct — BTC 2h move % that counts as drift even if the 1h stack has not turned yet',
  btc_drift_strong_ret_1h_pct: 'btc_drift_strong_ret_1h_pct — BTC 1h move % that counts as drift even if the 1h stack has not turned yet',
  paper_track_blocked: 'paper_track_blocked — Master switch for paper trades (signals blocked by one filter; no orders)',
  paper_track_rr_rejects: 'paper_track_rr_rejects — Paper-track trend signals rejected ONLY by net R:R (all other gates passed)',
  paper_track_slmin_rejects: 'paper_track_slmin_rejects — Trend signals rejected ONLY for SL below the minimum: paper-trade them with SL widened to the minimum and the smallest valid TP',
  paper_track_samedir_cap_rejects: 'paper_track_samedir_cap_rejects — Signals rejected ONLY by the "1 same-direction position when BTC is weak" cap: paper-trade them',
  paper_track_overext_rejects: 'paper_track_overext_rejects — Trend signals rejected ONLY as "overextended" (≥1.25 ATR from mean): paper-trade them, split strong vs normal trend',
  overext_strong_er: 'overext_strong_er — "Very strong trend" definition: symbol 1h ER at least this',
  overext_strong_adx: 'overext_strong_adx — "Very strong trend" definition: symbol 1h ADX at least this',
  // V.2.10.100
  pre_order_slip_band_pct: 'pre_order_slip_band_pct — Range: skip the order if the post-fill guard would fail within ±this % of the live price (saves instant-cancel fees)',
  range_exit_ignore_regime: 'range_exit_ignore_regime — Range BE/profit-lock ignore regime_adverse (default OFF = .99 behavior; turn on only after reviewing the ledger)',
  enable_weak_trend: 'enable_weak_trend — Reduced-size trend when the symbol is healthy and BTC is WEAK/CHOP',
  weak_trend_size_mult: 'weak_trend_size_mult — Size multiplier for weak_trend',
  weak_trend_min_confluence: 'weak_trend_min_confluence — Min score for weak_trend',
  weak_trend_min_adx: 'weak_trend_min_adx — Min symbol ADX for weak_trend (BTC ADX floor is skipped)',
  weak_trend_max_loss_usdt: 'weak_trend_max_loss_usdt — Max estimated loss after min-notional bump',

  // Anti-noise / trend quality (.90–.92)
  enable_ci_noise_filter: 'enable_ci_noise_filter — Reject high CI (choppy) setups',
  ci_noise_max: 'ci_noise_max — Max CI before noise reject',
  enable_er_noise_filter: 'enable_er_noise_filter — Reject low-efficiency (noisy) ER',
  er_noise_max: 'er_noise_max — Max ER labeled as noise (below = noisy)',
  enable_alt_er_strict: 'enable_alt_er_strict — Stricter min ER for alts',
  alt_er_min: 'alt_er_min — Min ER for alt entry when strict',
  enable_trend_quality_gate: 'enable_trend_quality_gate — Trend quality pre-entry gate',
  enable_trend_transition_guard: 'enable_trend_transition_guard — Block entry near trend transition',
  enable_candle_noise_filter: 'enable_candle_noise_filter — Wick/range candle noise filter',
  enable_entry_candle_confirm: 'enable_entry_candle_confirm — Require closed candle confirmation',
  enable_real_m5_closed_trigger: 'enable_real_m5_closed_trigger — Reject m15-only triggers (need closed 5m)',
  anti_noise_fail_closed: 'anti_noise_fail_closed — ON=reject on kline parse error; OFF=fail-open on parse only',

  // Live WR / probation
  live_wr_block_min_n: 'live_wr_block_min_n — Min live trades before WR block',
  live_wr_block_pct: 'live_wr_block_pct — Block symbol if live WR below this %',
  live_wr_probation_min_n: 'live_wr_probation_min_n — Min trades for probation sizing',
  live_wr_probation_pct: 'live_wr_probation_pct — WR below this → half size',
  live_wr_probation_size_mult: 'live_wr_probation_size_mult — Size multiplier on probation',

  // Post-profit hysteresis
  enable_post_profit_hysteresis: 'enable_post_profit_hysteresis — Cooldown after soft profit exit',
  post_profit_cooldown_sec: 'post_profit_cooldown_sec — Cooldown after profit exit (sec)',
  post_profit_hyst_window_sec: 'post_profit_hyst_window_sec — Hysteresis lookback window (sec)',
  post_profit_hyst_min_er_ratio: 'post_profit_hyst_min_er_ratio — Min ER ratio vs prior after profit',
  post_profit_hyst_min_adx_ratio: 'post_profit_hyst_min_adx_ratio — Min ADX ratio vs prior after profit',

  // Regime align / soft exit / stale
  enable_regime_align: 'enable_regime_align — Require regime alignment',
  regime_require_btc_align: 'regime_require_btc_align — Require BTC direction align',
  regime_require_symbol_htf: 'regime_require_symbol_htf — Require symbol HTF align',
  regime_min_adx: 'regime_min_adx — Min ADX for regime OK',
  enable_regime_soft_exit: 'enable_regime_soft_exit — Soft exit when regime turns adverse',
  enable_regime_adverse_loss_exit: 'enable_regime_adverse_loss_exit — Exit losers when regime turns adverse',
  regime_adverse_loss_min_elapsed_sec: 'regime_adverse_loss_min_elapsed_sec — Min hold before adverse exit (sec)',
  regime_adverse_loss_pnl_pct: 'regime_adverse_loss_pnl_pct — Max adverse PnL % to allow exit',
  regime_adverse_loss_min_conf: 'regime_adverse_loss_min_conf — Min regime conf for adverse exit',
  regime_adverse_btc_hostile: 'regime_adverse_btc_hostile — Treat hostile BTC regime as adverse',
  regime_exit_be_pct: 'regime_exit_be_pct — BE-style soft exit profit %',
  regime_exit_flat_min_elapsed: 'regime_exit_flat_min_elapsed — Min hold before flat soft exit (sec)',
  regime_exit_flat_min_pnl_pct: 'regime_exit_flat_min_pnl_pct — Min PnL % for flat soft exit',
  regime_exit_lock_progress: 'regime_exit_lock_progress — Progress-to-TP for regime lock exit',
  regime_exit_lock_min_profit: 'regime_exit_lock_min_profit — Min profit for regime lock exit',
  enable_stale_session_exit: 'enable_stale_session_exit — Close stale positions near session edge',
  stale_profit_min_pct: 'stale_profit_min_pct — Min profit % for stale profit exit',
  stale_neutral_min_pct: 'stale_neutral_min_pct — Band for stale neutral exit',
  stale_neutral_had_loss_pct: 'stale_neutral_had_loss_pct — Had-loss threshold for neutral stale',
  stale_flat_min_pct: 'stale_flat_min_pct — Flat band min % for stale flat exit',
  stale_flat_max_loss_usdt: 'stale_flat_max_loss_usdt — Max |loss| USDT for stale flat exit',
  stale_flat_exit_fee_est: 'stale_flat_exit_fee_est — Fee estimate for stale flat (USDT)',
  min_net_close_pnl_pct: 'min_net_close_pnl_pct — Min net PnL % for soft closes (fee-aware)',

  // News blackout
  enable_news_blackout: 'enable_news_blackout — Block entries around high-impact USD news',
  news_blackout_minutes_before: 'news_blackout_minutes_before — Tier A (or all, if tiering off): minutes before event',
  news_blackout_minutes_after: 'news_blackout_minutes_after — Tier A (or all, if tiering off): minutes after event',
  // V.2.11.2 — tiered news (crypto relevance)
  news_tiered: 'news_tiered — Tiered blackout: A (FOMC/CPI/NFP/Powell) full window, B (PCE/PPI/GDP/Retail/ISM/JOLTS/ADP) short, C (claims/S&P PMI/oil/housing…) no block',
  news_tier_b_minutes_before: 'news_tier_b_minutes_before — Tier B: minutes before event',
  news_tier_b_minutes_after: 'news_tier_b_minutes_after — Tier B: minutes after event',
  news_block_tier_c: 'news_block_tier_c — Also block tier C events (old behavior)',

  // Exit / profit
  profit_lock_trigger: 'profit_lock_trigger — Profit lock (progress to TP)',
  min_profit_pct: 'min_profit_pct — Min profit % to lock',
  breakeven_trigger_pct: 'breakeven_trigger_pct — Exchange BE price trigger % (not R)',
  breakeven_min_r: 'breakeven_min_r — Min R multiple before BE (V.2.10.94)',
  max_hold_seconds: 'max_hold_seconds — Max hold (sec)',
  float_min_r: 'float_min_r — Min float profit in R',
  float_min_profit_usdt: 'float_min_profit_usdt — Min float profit USDT',
  float_min_profit_pct: 'float_min_profit_pct — Min float profit %',
  float_min_elapsed_sec: 'float_min_elapsed_sec — Min time for float (sec)',
  enable_float_profit_exit: 'enable_float_profit_exit — Float profit exit',
  float_only_if_slots_full: 'float_only_if_slots_full — Float only if slots full',
  enable_regime_tighten_sl: 'enable_regime_tighten_sl — Tighten SL on adverse regime',
  regime_tighten_min_elapsed_sec: 'regime_tighten_min_elapsed_sec — Min time before tighten (sec)',
  regime_tighten_buffer_pct: 'regime_tighten_buffer_pct — Tighten buffer %',
  regime_tighten_only_if_loss: 'regime_tighten_only_if_loss — Tighten only if in loss',

  // Capital / risk
  daily_loss_limit: 'daily_loss_limit — Daily loss limit USDT',
  margin_fraction: 'margin_fraction — Margin fraction of equity',
  max_open_positions: 'max_open_positions — Max concurrent positions',
  leverage: 'leverage — Leverage',
  max_same_direction: 'max_same_direction — Max same-direction positions',
  enable_emergency_loss_exit: 'enable_emergency_loss_exit — Emergency loss exit',
  max_unrealized_loss_pct: 'max_unrealized_loss_pct — Max unrealized loss %',
  emergency_loss_min_elapsed_sec: 'emergency_loss_min_elapsed_sec — Min time for emergency (sec)',
  max_seconds_without_exchange_sl: 'max_seconds_without_exchange_sl — Max sec without exchange SL',
  global_sl_limit: 'global_sl_limit — SL count in window → global lock',
  global_sl_lookback_sec: 'global_sl_lookback_sec — Global SL lookback window (sec)',
  global_sl_lock_sec: 'global_sl_lock_sec — Global lock duration after cluster SL (sec)',
}

const GROUPS = [
  {
    title: 'Main control',
    keys: [
      'enable_new_entries',
      'auto_pause_entries_on_btc_regime',
      'auto_resume_min_btc_conf',
      'auto_pause_on_btc_bear_stack',
    ],
  },
  {
    title: 'Real entry',
    keys: [
      'min_confluence', 'min_sl_distance_pct', 'max_sl_distance_pct',
      'min_rr', 'round_trip_friction_pct', 'min_tp_distance_pct',
      'real_min_symbol_wr', 'symbol_cooldown_sec', 'post_close_cooldown_sec', 'post_sl_cooldown_sec',
      'post_negative_cooldown_sec', 'negative_pnl_threshold_usdt',
      'symbol_sl_lock_count', 'symbol_sl_lock_lookback_sec', 'symbol_sl_lock_sec',
      'enable_btc_chop_gate', 'btc_chop_block_alts', 'btc_weak_min_conf',
      'enable_chop_filter', 'chop_adx_threshold',
    ],
  },
  {
    title: 'ADX entry gate (blocks weak TREND_OK)',
    keys: [
      'enable_min_adx_entry',
      'min_adx_1h_for_entry',
      'min_btc_adx_1h_for_alt',
      'adx_strong_bypass_btc',
      'enable_strong_adx_bypass_btc_pause',
      'enable_adx_bypass_btc_chop',
    ],
  },
  {
    title: 'Range exits (2.11.8) — failed-entry exit, no early profit lock',
    keys: [
      'range_fail_exit',
      'range_fail_exit_min_sec',
      'range_fail_exit_mfe_max_pct',
      'range_fail_exit_adverse_r',
      'range_profit_lock',
      'range_small_tp_auto',
      'range_small_tp_min_n',
      'range_small_tp_min_delta_pp',
    ],
  },
  {
    title: 'Same-direction guard (2.11.6) — measured with paper trades',
    keys: [
      'underwater_block_same_dir',
      'underwater_min_loss_pct',
      'underwater_min_loss_usdt',
      'paper_track_underwater_rejects',
    ],
  },
  {
    title: 'Protected entry (2.11.3) — no bad fills',
    keys: [
      'entry_protected_ioc_selftest',
      'entry_protected_ioc',
      'entry_max_slippage_pct',
    ],
  },
  {
    title: 'BTC drift alignment (2.11) — trade with BTC, not against it',
    keys: [
      'btc_drift_guard_range',
      'btc_drift_min_ret_pct',
      'btc_drift_window_min',
      'btc_drift_trend_follow',
      'btc_drift_follow_min_symbol_conf',
      'btc_drift_same_dir_cap',
      'btc_drift_strong_ret_pct',
      'btc_drift_strong_ret_1h_pct',
      'paper_track_blocked',
      'paper_track_rr_rejects',
      'paper_track_slmin_rejects',
      'paper_track_samedir_cap_rejects',
      'paper_track_overext_rejects',
      'overext_strong_er',
      'overext_strong_adx',
    ],
  },
  {
    title: 'Range + weak trend (.98) — CHOP/WEAK scalps',
    keys: [
      'enable_range_scalp',
      'range_signal_only',
      'range_min_confluence',
      'range_max_sl_distance_pct',
      'range_min_rr',
      'range_min_tp_pct',
      'range_size_mult',
      'range_max_loss_usdt',
      'range_max_open_positions',
      'range_time_stop_sec',
      'range_win_cooldown_sec',
      'pre_order_slip_band_pct',
      'range_exit_ignore_regime',
      'range_ci_hard_max',
      'range_er_floor',
      'range_allow_btc_weak',
      'range_allow_btc_chop',
      'enable_weak_trend',
      'weak_trend_size_mult',
      'weak_trend_min_confluence',
      'weak_trend_min_adx',
      'weak_trend_max_loss_usdt',
    ],
  },
  {
    title: 'Anti-noise / trend quality (.90–.92)',
    keys: [
      'enable_ci_noise_filter', 'ci_noise_max',
      'enable_er_noise_filter', 'er_noise_max',
      'enable_alt_er_strict', 'alt_er_min',
      'enable_trend_quality_gate', 'enable_trend_transition_guard',
      'enable_candle_noise_filter', 'enable_entry_candle_confirm',
      'enable_real_m5_closed_trigger',
      'anti_noise_fail_closed',
    ],
  },
  {
    title: 'Live WR / probation',
    keys: [
      'live_wr_block_min_n', 'live_wr_block_pct',
      'live_wr_probation_min_n', 'live_wr_probation_pct', 'live_wr_probation_size_mult',
    ],
  },
  {
    title: 'Post-profit hysteresis',
    keys: [
      'enable_post_profit_hysteresis', 'post_profit_cooldown_sec',
      'post_profit_hyst_window_sec', 'post_profit_hyst_min_er_ratio', 'post_profit_hyst_min_adx_ratio',
    ],
  },
  {
    title: 'Regime align / soft exit / stale',
    keys: [
      'enable_regime_align', 'regime_require_btc_align', 'regime_require_symbol_htf', 'regime_min_adx',
      'enable_regime_soft_exit',
      'enable_regime_adverse_loss_exit', 'regime_adverse_loss_min_elapsed_sec',
      'regime_adverse_loss_pnl_pct', 'regime_adverse_loss_min_conf', 'regime_adverse_btc_hostile',
      'regime_exit_be_pct', 'regime_exit_flat_min_elapsed', 'regime_exit_flat_min_pnl_pct',
      'regime_exit_lock_progress', 'regime_exit_lock_min_profit',
      'enable_stale_session_exit',
      'stale_profit_min_pct', 'stale_neutral_min_pct', 'stale_neutral_had_loss_pct',
      'stale_flat_min_pct', 'stale_flat_max_loss_usdt', 'stale_flat_exit_fee_est',
      'min_net_close_pnl_pct',
    ],
  },
  {
    title: 'News blackout',
    keys: [
      'enable_news_blackout',
      'news_blackout_minutes_before',
      'news_blackout_minutes_after',
      'news_tiered',
      'news_tier_b_minutes_before',
      'news_tier_b_minutes_after',
      'news_block_tier_c',
    ],
  },
  {
    title: 'Exit / profit management',
    keys: [
      'profit_lock_trigger', 'min_profit_pct', 'breakeven_trigger_pct', 'breakeven_min_r', 'max_hold_seconds',
      'enable_float_profit_exit', 'float_only_if_slots_full', 'float_min_r', 'float_min_profit_usdt', 'float_min_profit_pct', 'float_min_elapsed_sec',
      'enable_regime_tighten_sl', 'regime_tighten_min_elapsed_sec', 'regime_tighten_buffer_pct', 'regime_tighten_only_if_loss',
    ],
  },
  {
    title: 'Capital & risk',
    keys: [
      'daily_loss_limit', 'margin_fraction', 'max_open_positions', 'leverage', 'max_same_direction',
      'enable_emergency_loss_exit', 'max_unrealized_loss_pct', 'emergency_loss_min_elapsed_sec', 'max_seconds_without_exchange_sl',
      'global_sl_limit', 'global_sl_lookback_sec', 'global_sl_lock_sec',
    ],
  },
]


export default function SettingsPanel() {
  const [settings, setSettings] = useState({})
  const [defaults, setDefaults] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew] = useState('')
  const [pwNew2, setPwNew2] = useState('')
  const [pwOverride, setPwOverride] = useState(false)

  const load = async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await authFetch(`${API_BASE_URL}/settings`)
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = data.detail || res.statusText || ''
        if (res.status === 404) {
          throw new Error(
            '/settings not found (404). Ensure settings_api router is mounted in app.py'
          )
        }
        throw new Error(`Load failed (${res.status}) ${detail}`)
      }
      setSettings(data.settings || {})
      setDefaults(data.defaults || {})
      setPwOverride(!!data.password_override_active)
    } catch (e) {
      setErr(e.message || 'Error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const setField = (key, value) => {
    setSettings((s) => ({ ...s, [key]: value }))
  }

  const save = async () => {
    setSaving(true)
    setMsg('')
    setErr('')
    try {
      const res = await authFetch(`${API_BASE_URL}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Save failed')
      setSettings(data.settings || settings)
      setMsg('Saved — applied to real trading immediately.')
    } catch (e) {
      setErr(e.message || 'Save error')
    } finally {
      setSaving(false)
    }
  }

  const changePassword = async () => {
    setMsg('')
    setErr('')
    if (pwNew.length < 4) {
      setErr('New password min 4 characters')
      return
    }
    if (pwNew !== pwNew2) {
      setErr('Password confirmation does not match')
      return
    }
    try {
      const res = await authFetch(`${API_BASE_URL}/settings/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: pwNew, current_password: pwCurrent }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Password change failed')
      setMsg(data.message || 'Password updated')
      setPwCurrent('')
      setPwNew('')
      setPwNew2('')
      setPwOverride(true)
    } catch (e) {
      setErr(typeof e.message === 'string' ? e.message : 'Error')
    }
  }

  const goHome = () => {
    window.location.hash = ''
    window.location.reload()
  }

  if (loading) {
    return (
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark">◈</span>
            <span className="brand-name">SignalDesk Settings</span>
          </div>
        </header>
        <main className="main"><p>Loading…</p></main>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <span className="brand-name">Settings</span>
        </div>
        <div className="topbar-status">
          <a
            href="#"
            className="topbar-admin-link"
            onClick={(e) => {
              e.preventDefault()
              goHome()
            }}
          >
            Back to home
          </a>
        </div>
      </header>

      <main className="main" style={{ maxWidth: 780, margin: '0 auto' }}>
        <section className="final-section" style={{ marginBottom: 16 }}>
          <p style={{ opacity: 0.85, lineHeight: 1.6 }}>
            Real-trading parameters. After save they apply immediately (no Relaunch).
            Extreme values can stop entries or increase risk.
            <br />
            <b dir="ltr">min_adx_1h_for_entry</b> is the real entry gate (default 20). <b dir="ltr">chop_adx_threshold</b> is legacy only. V.2.10.98 adds an independent range engine and a weak_trend path. Range orders are live unless <b dir="ltr">range_signal_only</b> is on. After deploy, set <b dir="ltr">range_min_rr</b> to 0.80 and Save — a stored 1.05 from .97 overrides the new default.
          </p>
          {msg && <p className="error-note" style={{ color: '#2DD4A7' }}>{msg}</p>}
          {err && <p className="error-note">{err}</p>}
        </section>

        {GROUPS.map((g) => (
          <section key={g.title} className="final-section" style={{ marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>{g.title}</h3>
            <div style={{ display: 'grid', gap: 12 }}>
              {g.keys.map((key) => {
                const val = settings[key]
                const isBool = typeof defaults[key] === 'boolean' || typeof val === 'boolean'
                return (
                  <label
                    key={key}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 12,
                      flexWrap: 'wrap',
                    }}
                  >
                    <span style={{ flex: 1, minWidth: 200, fontFamily: 'ui-monospace, monospace', fontSize: 13 }}>
                      {LABELS[key] || key}
                    </span>
                    {isBool ? (
                      <select
                        value={val ? '1' : '0'}
                        onChange={(e) => setField(key, e.target.value === '1')}
                        className="admin-pass-input"
                        style={{ width: 140 }}
                      >
                        <option value="1">ON</option>
                        <option value="0">OFF</option>
                      </select>
                    ) : (
                      <input
                        type="number"
                        step="any"
                        className="admin-pass-input"
                        style={{ width: 140 }}
                        value={val ?? ''}
                        onChange={(e) => {
                          const n = e.target.value
                          setField(key, n === '' ? '' : Number(n))
                        }}
                      />
                    )}
                  </label>
                )
              })}
            </div>
          </section>
        ))}

        <div style={{ display: 'flex', gap: 12, marginBottom: 28 }}>
          <button className="btn-primary" type="button" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save real settings'}
          </button>
          <button
            type="button"
            className="topbar-admin-link"
            onClick={() => setSettings({ ...defaults })}
          >
            Reset to defaults (not saved yet)
          </button>
        </div>

        <section className="final-section">
          <h3 style={{ marginTop: 0 }}>Site password</h3>
          <p style={{ opacity: 0.8, fontSize: 14 }}>
            Change the platform login password.
            {pwOverride
              ? ' File override is active.'
              : ' Currently using SITE_PASSWORD env secret.'}
            {' '}On HuggingFace, Persistent Storage is recommended for survival across restarts.
          </p>
          <div style={{ display: 'grid', gap: 10, maxWidth: 360 }}>
            <input
              type="password"
              className="admin-pass-input"
              placeholder="Current password (optional)"
              value={pwCurrent}
              onChange={(e) => setPwCurrent(e.target.value)}
            />
            <input
              type="password"
              className="admin-pass-input"
              placeholder="New password"
              value={pwNew}
              onChange={(e) => setPwNew(e.target.value)}
            />
            <input
              type="password"
              className="admin-pass-input"
              placeholder="Confirm new password"
              value={pwNew2}
              onChange={(e) => setPwNew2(e.target.value)}
            />
            <button className="btn-primary" type="button" onClick={changePassword}>
              Change password
            </button>
          </div>
        </section>
      </main>
    </div>
  )
}
