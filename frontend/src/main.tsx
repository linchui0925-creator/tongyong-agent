import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App.tsx'
import HomePage from './components/Home/HomePage'
import { ThemeProvider } from './theme/ThemeContext'
import './App.css'

// Allow a clean /app deep link without trailing slash weirdness.
const basename = (() => {
  // Vite injects BASE_URL; default to "/" for the dev server.
  // Using a runtime import.meta check keeps it build-safe.
  const base = (import.meta as { env?: { BASE_URL?: string } }).env?.BASE_URL ?? '/'
  return base === '/' ? '/' : base.replace(/\/$/, '')
})()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter basename={basename}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/app/*" element={<App />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
