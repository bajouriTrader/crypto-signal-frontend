// V.2.41.1 — «خط تصمیم ربات»: نمای ۶ مرحله‌ای (اسکنر، فیلتر ورود، اندازه، اجرا، دفتر، سرمایه) فقط از روی /real-trade/status.
// ماژول‌های قانون‌محورند، نه «ایجنت هوش مصنوعی». هیچ منطق معامله‌ای اینجا نیست.

const C = { green: '#2DD4A7', amber: '#F5A623', red: '#FF5C72', grey: '#5a6a7a' }
const FA = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹']

const num = (x) => {
  const n = Number(x)
  return Number.isFinite(n) ? n : null
}
const usd = (x, d = 2) => {
  const n = num(x)
  return n === null ? '—' : `${n >= 0 ? '' : '−'}${Math.abs(n).toFixed(d)}$`
}
const signed = (x, d = 2) => {
  const n = num(x)
  return n === null ? '—' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(d)}$`
}
const arr = (x) => (Array.isArray(x) ? x : [])

function ago(ts, now) {
  let t = num(ts)
  if (t === null || t <= 0) return null
  if (t > 1e12) t /= 1000
  const s = Math.max(0, now - t)
  if (s < 90) return `${Math.round(s)} ثانیه پیش`
  if (s < 5400) return `${Math.round(s / 60)} دقیقه پیش`
  if (s < 172800) return `${Math.round(s / 3600)} ساعت پیش`
  return `${Math.round(s / 86400)} روز پیش`
}

function scanText(r) {
  if (typeof r === 'string') return r
  if (r && typeof r === 'object') return `${r.slot_utc ?? '—'} ok=${r.fetch_ok ?? '—'}`
  return ''
}

export function buildAgents(s) {
  if (!s || typeof s !== 'object') return []
  const now = num(s.server_time) ?? Date.now() / 1000
  const gh = s.gh_entry || {}
  const L = s.github_strategies?.live
  const mgr = s.manager || {}
  const ef = s.entry_filters || {}
  const dp = s.daily_pnl || {}
  const lim = num(s.daily_loss_limit)
  const pnl = num(dp.pnl) ?? 0
  const loss = Math.max(0, -pnl)
  const out = []

  // ۱ — اسکنر
  {
    const ls = L?.last_scan || null
    const age = ls?.ts ? now - (num(ls.ts) ?? 0) : null
    const errs = arr(ls?.fetch_err)
    let dot = 'grey'
    if (L && L.enabled !== false && ls) {
      dot = age !== null && age < 1200 ? 'green' : age !== null && age < 3600 ? 'amber' : 'red'
      if (errs.length && dot === 'green') dot = 'amber'
    }
    const bt = s.backtest || {}
    const lines = [`${arr(gh.live).length} استراتژی زنده: ${arr(gh.live).join('، ') || '—'}`]
    const rec = arr(L?.scans_recent).slice(-3).map(scanText).filter(Boolean)
    if (rec.length) lines.push(`اخیر: ${rec.join(' · ')}`)
    lines.push(`بک‌تست: ${bt.state ?? '—'}${bt.finished_at ? ` (${ago(bt.finished_at, now)})` : ''}`)
    if (errs.length) lines.push(`خطای دریافت: ${errs.length}`)
    out.push({
      key: 'scan', fa: 'اسکنر', en: 'Scanner', dot, ts: ls?.ts,
      head: ls ? `اسکن ${ls.slot_utc ?? '—'} UTC · ${arr(ls.signals).length} سیگنال · ${arr(ls.opened).length} ورود` : 'هنوز اسکنی ثبت نشده',
      lines,
    })
  }

  // ۲ — فیلتر ورود
  {
    const nb = s.news_blackout || {}
    const chips = arr(s.entry_block_summary?.chips)
    let dot = 'green'
    if (!s.real_trading_enabled || s.enable_new_entries === false) dot = 'red'
    else if (lim !== null && loss >= lim) dot = 'red'
    else if (s.auto_entry_pause || nb.active || gh.blocked) dot = 'amber'
    const head = dot === 'red' && !s.real_trading_enabled ? 'معامله واقعی خاموش'
      : dot === 'red' && s.enable_new_entries === false ? 'ورود جدید خاموش'
      : dot === 'red' ? 'سقف ضرر روزانه پر شده'
      : gh.blocked ? (gh.why || gh.line || 'ورود بسته')
      : s.auto_entry_pause ? (s.auto_entry_pause_reason || 'pause ورود')
      : 'ورود آزاد'
    const lines = []
    if (nb.active) lines.push(`⛔ توقف خبری: ${nb.event_title || nb.event?.title_fa || '—'}`)
    else if (nb.next_event) lines.push(`خبر بعدی: ${nb.next_event.title_fa || nb.next_event.title || '—'}`)
    else lines.push('خبر مهمی در راه نیست')
    if (chips.length) lines.push(`${chips.filter((c) => c?.ok).length}/${chips.length} شرط موتور قدیمی OK`)
    out.push({ key: 'gate', fa: 'فیلتر ورود', en: 'Gate', dot, head, lines })
  }

  // ۳ — اندازهٔ پوزیشن
  {
    const eq = num(s.equity_usdt)
    const av = num(s.available_usdt)
    const lev = num(s.leverage)
    const mm = num(ef.min_margin_usdt)
    const mn = num(ef.min_notional_usdt)
    let dot = eq === null ? 'grey' : 'green'
    if (av !== null && ((mm !== null && av < mm) || (lev && mn !== null && av * lev < mn))) dot = 'amber'
    const lines = [`آزاد ${usd(av)} · اسلات GH ${gh.open ?? '—'}/${gh.max ?? '—'} · کل ${s.open_positions ?? '—'}/${s.max_open_positions ?? '—'}`]
    if (mm !== null || mn !== null) lines.push(`حداقل مارجین ${usd(mm)} · حداقل حجم ${usd(mn)}`)
    out.push({
      key: 'size', fa: 'اندازه پوزیشن', en: 'Sizer', dot,
      head: `${usd(eq)} · ${lev ?? '—'}x · پایه: ${s.sizing_basis === 'equity' ? 'موجودی' : (s.sizing_basis ?? '—')}`,
      lines,
    })
  }

  // ۴ — اجرا
  {
    const tr = arr(s.tracked)
    const hb = s.manager_heartbeat || {}
    const lag = num(hb.last_cycle_ago_sec)
    const iv = num(mgr.interval_seconds) ?? 45
    let dot = 'green'
    if (lag === null || lag > 3 * iv) dot = 'red'
    else if (tr.some((t) => t?.sl_on_exchange === false)) dot = 'amber'
    const open = tr.reduce((a, t) => a + (num(t?.unrealized_usdt) ?? 0), 0)
    const lines = tr.slice(0, 2).map((t) => `${t?.symbol ?? '—'} ${t?.direction ?? ''} · ${t?.strategy_id ?? '—'} · ${signed(t?.unrealized_usdt)}`)
    if (tr.some((t) => t?.sl_on_exchange === false)) lines.push('⚠️ پوزیشن بدون حد ضرر روی صرافی')
    lines.push(`مدیر پوزیشن: چرخهٔ ${hb.cycles_since_boot ?? '—'} از ری‌استارت`)
    out.push({
      key: 'exec', fa: 'اجرا', en: 'Executor', dot,
      ts: lag !== null ? now - lag : null,
      head: tr.length ? `${tr.length} پوزیشن باز · PnL باز ${signed(open)}` : 'منتظر سیگنال',
      lines,
    })
  }

  // ۵ — دفتر معاملات
  {
    const lr = s.ledger_recent || {}
    const it = arr(lr.items)[0]
    const rc = arr(s.recent_closed)[0]
    const has = !!(it || rc)
    const lines = []
    if (it) lines.push(`آخرین: ${it.symbol ?? '—'} ${it.direction ?? ''} ${signed(it.pnl_usdt)} · ${it.exit_reason ?? '—'}`)
    else if (rc) lines.push(`آخرین: ${rc.symbol ?? '—'} ${rc.direction ?? ''} ${signed(rc.approx_pnl)}`)
    if (lr.fees_usdt != null) lines.push(`کارمزد ${lr.count ?? '—'} معاملهٔ اخیر: ${usd(lr.fees_usdt)}`)
    out.push({
      key: 'log', fa: 'دفتر معاملات', en: 'Logger', dot: has ? 'green' : 'grey',
      ts: it?.closed_at ?? rc?.closed_at,
      head: lr.count != null
        ? `${lr.count} اخیر: ${lr.wins ?? 0} برد / ${lr.losses ?? 0} باخت / ${lr.scratches ?? 0} سربه‌سر · ${signed(lr.net_pnl_usdt)}`
        : 'دفتر خالی',
      headColor: num(lr.net_pnl_usdt) > 0 ? C.green : num(lr.net_pnl_usdt) < 0 ? C.red : undefined,
      lines,
    })
  }

  // ۶ — سرمایه
  {
    const eq = num(s.equity_usdt)
    let dot = eq === null ? 'grey' : 'green'
    if (lim !== null && lim > 0) {
      if (loss >= lim) dot = 'red'
      else if (loss >= 0.66 * lim) dot = 'amber'
    }
    out.push({
      key: 'eq', fa: 'سرمایه', en: 'Equity', dot, ts: dp.refreshed_at,
      head: `${usd(eq)} · امروز ${signed(pnl)}`,
      headColor: pnl > 0 ? C.green : pnl < 0 ? C.red : undefined,
      lines: [lim !== null ? `سقف ضرر روزانه ${usd(lim)} · باقی‌مانده ${usd(Math.max(0, lim - loss))}` : 'سقف ضرر روزانه: —',
        `منبع: ${dp.source === 'exchange' ? 'صرافی' : (dp.source ?? '—')}`],
    })
  }

  return out.map((a) => ({ ...a, ago: ago(a.ts, now) }))
}

export default function AgentPipeline({ status }) {
  let agents = []
  try {
    agents = buildAgents(status)
  } catch {
    agents = []
  }
  if (!agents.length) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: '#8899aa', marginBottom: 6, textAlign: 'right' }}>
        خط تصمیم ربات — ۶ مرحله <span style={{ color: '#5a6a7a' }}>(قانون‌محور، بدون هوش مصنوعی)</span>
      </div>
      <div className="rt-agents" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {agents.map((a, i) => (
          <div
            key={a.key}
            style={{
              minWidth: 0,
              padding: '8px 10px',
              borderRadius: 10,
              background: '#121c28',
              border: `1px solid ${a.dot === 'red' ? '#5a2430' : a.dot === 'amber' ? '#4a3a1a' : '#243444'}`,
              fontSize: 11,
              lineHeight: 1.6,
              textAlign: 'right',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <span
                style={{
                  width: 18, height: 18, borderRadius: 9, background: '#1e3344', color: '#9fb3c8',
                  fontSize: 10, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}
              >
                {FA[i + 1]}
              </span>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: C[a.dot] || C.grey, flexShrink: 0 }} />
              <span style={{ fontWeight: 700, color: '#e0f0ff', fontSize: 12 }}>{a.fa}</span>
              <span className="rt-agent-en" style={{ color: '#5a6a7a', fontSize: 10 }} dir="ltr">{a.en}</span>
              {a.ago && <span style={{ marginRight: 'auto', color: '#6a7a8a', fontSize: 10, whiteSpace: 'nowrap' }}>{a.ago}</span>}
            </div>
            <div
              style={{
                color: a.headColor || '#e8f0f8', fontWeight: 600, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
              title={a.head}
            >
              <bdi>{a.head}</bdi>
            </div>
            {a.lines.map((ln, k) => (
              <div key={k} style={{ color: '#8899aa', overflowWrap: 'anywhere' }}>
                <bdi>{ln}</bdi>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
