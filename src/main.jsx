import React, { useState } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import AdminPanel from './AdminPanel.jsx'
import SettingsPanel from './SettingsPanel.jsx'
import Login from './Login.jsx'
import { getToken } from './auth.js'
import './index.css'

function Root() {
  const [authed, setAuthed] = useState(!!getToken())

  if (!authed) {
    return <Login onSuccess={() => setAuthed(true)} />
  }

  const hash = window.location.hash || ''
  let RootComponent = App
  if (hash.startsWith('#admin')) RootComponent = AdminPanel
  else if (hash.startsWith('#settings')) RootComponent = SettingsPanel

  return <RootComponent />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
