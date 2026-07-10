import React, { useState } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import AdminPanel from './AdminPanel.jsx'
import Login from './Login.jsx'
import { getToken } from './auth.js'
import './index.css'

function Root() {
  const [authed, setAuthed] = useState(!!getToken())

  if (!authed) {
    return <Login onSuccess={() => setAuthed(true)} />
  }

  const RootComponent = window.location.hash === '#admin' ? AdminPanel : App
  return <RootComponent />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
