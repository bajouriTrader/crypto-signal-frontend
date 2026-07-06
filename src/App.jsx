import { useState, useRef } from 'react'

// ---- Mock data (placeholder until backend from Phase 3 is wired in) ----
const MOCK_MODELS = [
  {
    id: 'gpt',
    name: 'GPT-4o',
    provider: 'GitHub Models',
    accent: '#2DD4A7',
    verdict: 'ورود',
    winRate: 68,
    methods: [
      { name: 'ICT', score: 71 },
      { name: 'SMC', score: 65 },
      { name: 'Liquidity Sweep', score: 74 },
      { name: 'VWAP', score: 62 },
    ],
    note: 'واکنش قیمت به liquidity sweep زیر لو قبلی با تایید حجم همراه بوده.',
  },
  {
    id: 'llama',
    name: 'Llama 3.3 70B',
    provider: 'Groq',
    accent: '#E8A94A',
    verdict: 'محتاطانه',
    winRate: 54,
    methods: [
      { name: 'ICT', score: 58 },
      { name: 'SMC', score: 49 },
      { name: 'Liquidity Sweep', score: 60 },
      { name: 'VWAP', score: 51 },
    ],
    note: 'ساختار روند اصلی هنوز نزولی است؛ سیگنال بیشتر ضدروند به‌نظر می‌رسد.',
  },
  {
    id: 'gemini',
    name: 'Gemini',
    provider: 'Google AI Studio',
    accent: '#2DD4A7',
    verdict: 'ورود',
    winRate: 71,
    methods: [
      { name: 'ICT', score: 76 },
      { name: 'SMC', score: 70 },
      { name: 'Liquidity Sweep', score: 78 },
      { name: 'VWAP', score: 60 },
    ],
    note: 'همخوانی خوبی با الگوی Order Block و بازگشت از ناحیه تقاضا دارد.',
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    provider: 'DeepSeek Platform',
    accent: '#FF5C72',
    verdict: 'عدم ورود',
    winRate: 39,
    methods: [
      { name: 'ICT', score: 41 },
      { name: 'SMC', score: 35 },
      { name: 'Liquidity Sweep', score: 44 },
      { name: 'VWAP', score: 36 },
    ],
    note: 'نسبت ریسک به ریوارد با فاصله SL فعلی توجیه‌پذیر نیست.',
  },
]

const FINAL_VERDICT = {
  decision: 'ورود با احتیاط',
  winRate: 58,
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
  const fileInputRef = useRef(null)

  const canAnalyze =
    (mode === 'text' && signalText.trim().length > 0) ||
    (mode === 'image' && imageFile !== null)

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) setImageFile(file)
  }

  const handleAnalyze = () => {
    if (!canAnalyze) return
    setStatus('analyzing')
    // Placeholder: Phase 3 will replace this with the real backend call
    // (fan-out to 4 models x 4 methods, then the platform's synthesis).
    setTimeout(() => setStatus('done'), 1400)
  }

  const handleReset = () => {
    setStatus('idle')
    setSignalText('')
    setImageFile(null)
  }

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
              {status === 'analyzing' ? 'در حال تحلیل…' : 'شروع تحلیل'}
            </button>
            {status === 'done' && (
              <button className="btn-ghost" onClick={handleReset}>
                سیگنال جدید
              </button>
            )}
          </div>
        </section>

        {status === 'done' && (
          <>
            <section className="results-note">
              <span className="results-note-badge">داده نمایشی</span>
              این نتایج فعلاً نمونه هستن — در فاز بعد به بک‌اند واقعی وصل
              می‌شن.
            </section>

            <section className="model-grid">
              {MOCK_MODELS.map((m) => (
                <ModelCard key={m.id} model={m} />
              ))}
            </section>

            <section className="final-section">
              <ConfluenceMeter models={MOCK_MODELS} final={FINAL_VERDICT} />
            </section>
          </>
        )}
      </main>

      <footer className="footer">
        هیچ خروجی این پلتفرم توصیه مالی نیست — تصمیم ورود همیشه با خودته.
      </footer>
    </div>
  )
}
