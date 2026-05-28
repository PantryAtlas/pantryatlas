/// <reference types="vite/client" />
import { render, h, Fragment } from 'preact'
import './styles/global.css'
import { InstallPrompt } from './components/InstallPrompt'
import { Navigator } from './pages/Navigator'

function App() {
  return (
    <Fragment>
      <Navigator />
      <InstallPrompt />
    </Fragment>
  )
}

render(<App />, document.getElementById('app')!)

// Register service worker in production only.
// Dev skips registration so HMR isn't intercepted by the SW fetch handler.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((err) => {
      console.warn('[PantryAtlas] SW registration failed:', err)
    })
  })
}
