import { authFetch } from './auth'
import { useState, useRef } from 'react'
import SignalChart from './SignalChart'
import AutoSignalList, { DemoTradePanel, SendToExchangeButton } from './AutoSignalList'
import OpenPositionsPanel from './OpenPositionsPanel'

// آدرس بک‌اند (فاز ۳) روی HuggingFace Spaces
const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

// اطلاعات نمایشی هر مدل (اسم، نام ارائه‌دهنده، رنگ) — چون بک‌اند فقط کلید
// فنی مثل "github" یا "groq" برمی‌گردونه
const PROVIDER_META = {
  github: { name: 'GPT-4o', provider: 'GitHub Models', accent: '#2DD4A7' },
  groq: { name: 'Llama 3.3 70B', provider: 'Groq', accent: '#E8A94A' },
  gemini: { name: 'Gemini', provider: 'Google AI Studio', accent: '#2DD4A7' },
  deepseek: { name: 'DeepSeek', provider: 'DeepSeek Platform', accent: '#FF5C72' },
}

const METHOD_LABELS = {
  ict: 'ICT',
  smc: 'SMC',
  liquidity_sweep: 'Liquidity Sweep',
  vwap: 'VWAP',
}

// تبدیل پاسخ خام بک‌اند به ساختاری که کامپوننت‌های نمایشی انتظار دارن
function mapModelResults(modelResults) {
  return Object.entries(PROVIDER_META).map(([key, meta]) => {
    const methodsData = modelResults?.[key] || {}

    const methods = Object.entries(METHOD_LABELS).map(([mKey, mLabel]) => {
      const r = methodsData[mKey]
      const hasScore = r && typeof r.quality_score === 'number'
      return { name: mLabel, score: hasScore ? r.quality_score : null }
    })

    const validScores = methods
      .map((m) => m.score)
      .filter((s) => typeof s === 'number')

    const winRate = validScores.length
      ? Math.round(validScores.reduce((a, b) => a + b, 0) / validScores.length)
      : null

    let verdict = 'داده ناقص'
    if (winRate !== null) {
      verdict = winRate >= 65 ? 'ورود' : winRate >= 45 ? 'محتاطانه' : 'عدم ورود'
    }

    const firstSuccess = Object.values(methodsData).find((r) => r?.reasoning)
    const note = firstSuccess
      ? firstSuccess.reasoning
      : 'این مدل برای این سیگنال پاسخ معتبری برنگردوند (خطای موقت سرویس یا محدودیت سهمیه).'

    return {
      id: key,
      name: meta.name,
      provider: meta.provider,
      accent: meta.accent,
      verdict,
      winRate: winRate ?? 0,
      methods: methods.map((m) => ({ name: m.name, score: m.score ?? 0 })),
      note,
    }
  })
}

function buildFinalVerdict(finalVerdictData) {
  const score = finalVerdictData?.signal_quality_score
  if (score === null || score === undefined) {
    return { decision: 'داده کافی برای جمع‌بندی نیست', winRate: 0 }
  }
  const decision = score >= 65 ? 'ورود' : score >= 45 ? 'ورود با احتیاط' : 'عدم ورود'
  return { decision, winRate: Math.round(score) }
}

// ساخت شیء سیگنال با شکل موردنیاز DemoTradePanel/SendToExchangeButton، از
// روی parsed_signal که بک‌اند برای تحلیل دستی برمی‌گردونه (entries[]/targets[])
function buildManualDemoSignal(parsedSignal) {
  if (!parsedSignal?.symbol || !parsedSignal?.direction) return null
  const entry = Array.isArray(parsedSignal.entries) ? parsedSignal.entries[0] : parsedSignal.entry
  const target = Array.isArray(parsedSignal.targets) ? parsedSignal.targets[0] : parsedSignal.target
  const stopLoss = parsedSignal.stop_loss
  if (entry == null || target == null || stopLoss == null) return null

  return {
    symbol: parsedSignal.symbol,
    direction: parsedSignal.direction,
    entry,
    target,
    stop_loss: stopLoss,
    suggested_leverage: parsedSignal.leverage || 5,
    // سیگنال‌های وارد‌شده‌ی دستی از کسکید ۶ تایم‌فریمی رد نشدن، پس نه
    // «سخت‌گیر»ان نه «ساده‌گیر» — به‌همین دلیل به‌عنوان حالت جدا برچسب می‌خورن
    mode: 'manual',
    max_hold_hours: 4,
  }
}

function ConfluenceMeter({ models, final }) {
  return (
    <div className="meter">
      <div className="meter-labels">
        <span>عدم ورود</span>
        <span>ورود</span>
      </div>
      <div className="meter-track">
        <div className="meter-fill" style={{ width: `${final.winRate}%` }} />
        {models.map((m) => (
          <div
            key={m.id}
            className="meter-tick"
            style={{ left: `${m.winRate}%`, background: m.accent }}
            title={`${m.name}: ${m.winRate}%`}
          />
        ))}
        <div className="meter-needle" style={{ left: `${final.winRate}%` }} />
      </div>
      <div className="meter-final">
        <span className="meter-final-label">نظر نهایی پلتفرم</span>
        <span dir="ltr" className="meter-final-value">
          {final.winRate}%
        </span>
        <span className="meter-final-decision">{final.decision}</span>
      </div>
    </div>
  )
}

function ModelCard({ model }) {
  const verdictClass =
    model.verdict === 'ورود'
      ? 'verdict-in'
      : model.verdict === 'عدم ورود'
      ? 'verdict-out'
      : 'verdict-caution'

  return (
    <div className="model-card" style={{ '--accent': model.accent }}>
      <div className="model-card-head">
        <div>
          <div className="model-name">{model.name}</div>
          <div className="model-provider">{model.provider}</div>
        </div>
        <div dir="ltr" className="model-winrate">
          {model.winRate}%
        </div>
      </div>

      <span className={`verdict-badge ${verdictClass}`}>{model.verdict}</span>

      <div className="method-list">
        {model.methods.map((meth) => (
          <div className="method-row" key={meth.name}>
            <span className="method-name">{meth.name}</span>
            <div className="method-bar-track">
              <div
                className="method-bar-fill"
                style={{ width: `${meth.score}%` }}
              />
            </div>
            <span dir="ltr" className="method-score">
              {meth.score}
            </span>
          </div>
        ))}
      </div>

      <p className="model-note">{model.note}</p>
    </div>
  )
}

export default function App() {
  const [mode, setMode] = useState('text') // 'text' | 'image'
  const [signalText, setSignalText] = useState('')
  const [imageFile, setImageFile] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const [status, setStatus] = useState('idle') // 'idle' | 'analyzing' | 'done'
  const [errorMsg, setErrorMsg] = useState('')
  const [models, setModels] = useState([])
  const [finalVerdict, setFinalVerdict] = useState(null)
  const [aiSummary, setAiSummary] = useState('')
  const [parsedSignal, setParsedSignal] = useState(null)
  const fileInputRef = useRef(null)
  const resultsRef = useRef(null)

  const canAnalyze =
    (mode === 'text' && signalText.trim().length > 0) ||
    (mode === 'image' && imageFile !== null)

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) setImageFile(file)
  }

  const handleAnalyze = async () => {
    if (!canAnalyze) return

    if (mode === 'image') {
      setErrorMsg(
        'آپلود تصویر فعلاً پشتیبانی نمی‌شه — لطفاً فعلاً متن سیگنال رو وارد کن.'
      )
      return
    }

    setErrorMsg('')
    setStatus('analyzing')

    try {
      const res = await authFetch(`${API_BASE_URL}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ signal_text: signalText }),
      })

      if (!res.ok) {
        throw new Error(`خطای سرور (کد ${res.status})`)
      }

      const data = await res.json()
      setModels(mapModelResults(data.model_results))
      setFinalVerdict(buildFinalVerdict(data.final_verdict))
      setAiSummary(data.final_verdict?.ai_summary || '')
      setParsedSignal(data.parsed_signal || null)
      setStatus('done')
    } catch (err) {
      setErrorMsg(
        'تحلیل سیگنال با خطا مواجه شد. لطفاً دوباره امتحان کن. (' +
          err.message +
          ')'
      )
      setStatus('idle')
    }
  }

  const handleAutoAnalyze = async (symbol, signalMode = 'relaxed') => {
    setErrorMsg('')
    setStatus('analyzing')
    setMode('text')

    try {
      const res = await authFetch(`${API_BASE_URL}/auto-signal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, mode: signalMode }),
      })

      if (!res.ok) {
        throw new Error(`خطای سرور (کد ${res.status})`)
      }

      const data = await res.json()
      setSignalText(data.signal_text || '')
      setModels(mapModelResults(data.model_results))
      setFinalVerdict(buildFinalVerdict(data.final_verdict))
      setAiSummary(data.final_verdict?.ai_summary || '')
      setParsedSignal(data.parsed_signal || null)
      setStatus('done')
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)
    } catch (err) {
      setErrorMsg(
        'تحلیل خودکار با خطا مواجه شد. لطفاً دوباره امتحان کن. (' +
          err.message +
          ')'
      )
      setStatus('idle')
    }
  }

  const handleReset = () => {
    setStatus('idle')
    setSignalText('')
    setImageFile(null)
    setModels([])
    setFinalVerdict(null)
    setAiSummary('')
    setParsedSignal(null)
    setErrorMsg('')
  }

  const manualDemoSignal = buildManualDemoSignal(parsedSignal)

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <span className="brand-name">SignalDesk</span>
        </div>
        <div className="topbar-status">
          <span className="dot" />
          <span>۴ مدل هوش مصنوعی آماده تحلیل</span>
        </div>
      </header>

      <main className="main">
        <OpenPositionsPanel />

        <section className="intake">
          <h1 className="intake-title">سیگنال رو بذار روی میز</h1>
          <p className="intake-sub">
            متن سیگنال رو وارد کن یا اسکرین‌شاتش رو رها کن — نتیجه‌ی ۴ مدل و
            جمع‌بندی نهایی رو می‌بینی.
          </p>

          <div className="tabs">
            <button
              className={`tab ${mode === 'text' ? 'tab-active' : ''}`}
              onClick={() => setMode('text')}
            >
              ورود متنی
            </button>
            <button
              className={`tab ${mode === 'image' ? 'tab-active' : ''}`}
              onClick={() => setMode('image')}
            >
              آپلود تصویر
            </button>
          </div>

          {mode === 'text' ? (
            <textarea
              className="signal-input"
              placeholder={
                'مثال:\nXLM — SHORT\nENTRY: 0.1842 - 0.1875\nTARGET: 0.1825 / 0.1800 / 0.1785\nSL: 0.1973\nLEVERAGE: 10x'
              }
              dir="ltr"
              value={signalText}
              onChange={(e) => setSignalText(e.target.value)}
            />
          ) : (
            <div
              className={`dropzone ${isDragging ? 'dropzone-active' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                hidden
                onChange={(e) => setImageFile(e.target.files?.[0] ?? null)}
              />
              {imageFile ? (
                <span className="dropzone-filename">{imageFile.name}</span>
              ) : (
                <>
                  <span className="dropzone-icon">＋</span>
                  <span>عکس سیگنال رو اینجا رها کن یا کلیک کن</span>
                </>
              )}
            </div>
          )}

          <div className="intake-actions">
            <button
              className="btn-primary"
              disabled={!canAnalyze || status === 'analyzing'}
              onClick={handleAnalyze}
            >
              {status === 'analyzing' ? 'در حال تحلیل… (تا ۳۰ ثانیه)' : 'شروع تحلیل'}
            </button>
            {status === 'done' && (
              <button className="btn-ghost" onClick={handleReset}>
                سیگنال جدید
              </button>
            )}
          </div>

          {errorMsg && <p className="error-note">{errorMsg}</p>}
        </section>

        <AutoSignalList
          onFullAnalyze={handleAutoAnalyze}
          isAnalyzing={status === 'analyzing'}
        />

        {status === 'analyzing' && (
          <div className="analyzing-banner">
            ⏳ در حال تحلیل با ۴ هوش مصنوعی… (تا ۳۰ ثانیه طول می‌کشه)
          </div>
        )}

        {status === 'done' && finalVerdict && (
          <>
            <div ref={resultsRef} />
            {parsedSignal?.symbol && (
              <div className="results-heading">
                نتایج تحلیل برای:{' '}
                <span className="results-heading-symbol">{parsedSignal.symbol}</span>
                <span
                  className={`results-heading-direction ${
                    parsedSignal.direction === 'short' ? 'dir-short' : 'dir-long'
                  }`}
                >
                  {parsedSignal.direction === 'short' ? 'شورت' : 'لانگ'}
                </span>
              </div>
            )}

            <section className="model-grid">
              {models.map((m) => (
                <ModelCard key={m.id} model={m} />
              ))}
            </section>

            <section className="final-section">
              <ConfluenceMeter models={models} final={finalVerdict} />
              {aiSummary && (
                <div className="ai-summary">
                  <div className="ai-summary-title">جمع‌بندی تحلیلی</div>
                  <p>{aiSummary}</p>
                </div>
              )}

              {manualDemoSignal && (
                <div className="watchlist-actions">
                  <SendToExchangeButton symbol={manualDemoSignal.symbol} hasSignal={true} />
                  <DemoTradePanel signal={manualDemoSignal} initialOpenTrade={null} />
                </div>
              )}
            </section>

            {parsedSignal && <SignalChart parsedSignal={parsedSignal} />}
          </>
        )}
      </main>

      <footer className="footer">
        هیچ خروجی این پلتفرم توصیه مالی نیست — تصمیم ورود همیشه با خودته.
      </footer>
    </div>
  )
}
