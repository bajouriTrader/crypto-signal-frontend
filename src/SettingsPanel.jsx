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
  regime_exit_be_pct: 'regime_exit_be_pct — BE-style soft exit profit %',
  regime_exit_flat_min_elapsed: 'regime_exit_flat_min_elapsed — Min hold before flat soft exit (sec)',
  regime_exit_flat_min_pnl_pct: 'regime_exit_flat_min_pnl_pct — Min PnL % for flat soft exit',
  regime_exit_lock_progress: 'regime_exit_lock_progress — Progress-to-TP for regime lock exit',
  regime_exit_lock_min_profit: 'regime_exit_lock_min_profit — Min profit for regime lock exit',
  enable_stale_session_exit: 'enable_stale_session_exit — Close stale positions near session edge',
  stale_profit_min_pct: 'stale_profit_min_pct — Min profit % for stale profit exit',
  stale_neutral_min_pct: 'stale_neutral_min_pct — Band for stale neutral exit',
  stale_neutral_had_loss_pct: 'stale_neutral_had_loss_pct — Had-loss threshold for neutral stale',
  min_net_close_pnl_pct: 'min_net_close_pnl_pct — Min net PnL % for soft closes (fee-aware)',

  // News blackout
  enable_news_blackout: 'enable_news_blackout — Block entries around high-impact USD news',
  news_blackout_minutes_before: 'news_blackout_minutes_before — Minutes before event',
  news_blackout_minutes_after: 'news_blackout_minutes_after — Minutes after event',

  // Exit / profit
  profit_lock_trigger: 'profit_lock_trigger — Profit lock (progress to TP)',
  min_profit_pct: 'min_profit_pct — Min profit % to lock',
  breakeven_trigger_pct: 'breakeven_trigger_pct — Exchange BE trigger %',
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
      'regime_exit_be_pct', 'regime_exit_flat_min_elapsed', 'regime_exit_flat_min_pnl_pct',
      'regime_exit_lock_progress', 'regime_exit_lock_min_profit',
      'enable_stale_session_exit',
      'stale_profit_min_pct', 'stale_neutral_min_pct', 'stale_neutral_had_loss_pct',
      'min_net_close_pnl_pct',
    ],
  },
  {
    title: 'News blackout',
    keys: [
      'enable_news_blackout',
      'news_blackout_minutes_before',
      'news_blackout_minutes_after',
    ],
  },
  {
    title: 'Exit / profit management',
    keys: [
      'profit_lock_trigger', 'min_profit_pct', 'breakeven_trigger_pct', 'max_hold_seconds',
      'enable_float_profit_exit', 'float_only_if_slots_full', 'float_min_r', 'float_min_profit_usdt', 'float_min_profit_pct', 'float_min_elapsed_sec',
      'enable_regime_tighten_sl', 'regime_tighten_min_elapsed_sec', 'regime_tighten_buffer_pct', 'regime_tighten_only_if_loss',
    ],
  },
  {
    title: 'Capital & risk',
    keys: [
      'daily_loss_limit', 'margin_fraction', 'max_open_positions', 'leverage', 'max_same_direction',
      'enable_emergency_loss_exit', 'max_unrealized_loss_pct', 'emergency_loss_min_elapsed_sec', 'max_seconds_without_exchange_sl',
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
            <b dir="ltr">min_adx_1h_for_entry</b> is the real entry gate (default 25). <b dir="ltr">chop_adx_threshold</b> is legacy only. Anti-noise block includes <b dir="ltr">anti_noise_fail_closed</b> and <b dir="ltr">enable_real_m5_closed_trigger</b>.
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
