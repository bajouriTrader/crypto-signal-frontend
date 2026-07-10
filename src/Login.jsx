import { useState } from 'react'
import { setToken } from './auth'

const API_BASE_URL = 'https://asalehb-crypto-signal-backend.hf.space'

export default function Login({ onSuccess }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    if (!password) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (!res.ok) throw new Error('bad')
      const data = await res.json()
      setToken(data.token)
      onSuccess()
    } catch {
      setError('رمز اشتباهه یا مشکلی توی اتصال پیش اومد.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="admin-gate">
      <h2>ورود به پلتفرم</h2>
      <input
        type="password"
        className="admin-pass-input"
        placeholder="رمز عبور"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
        autoFocus
      />
      <button className="btn-primary" onClick={handleLogin} disabled={loading}>
        {loading ? 'در حال بررسی…' : 'ورود'}
      </button>
      {error && <p className="error-note">{error}</p>}
    </div>
  )
}
