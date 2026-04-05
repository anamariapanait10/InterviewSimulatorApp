import { NavLink, Outlet } from 'react-router-dom'
import './App.css'

export default function App() {
  return (
    <div className="app-shell">
      <div className="ambient-orb ambient-orb-one" />
      <div className="ambient-orb ambient-orb-two" />

      <header className="app-nav-wrap">
        <NavLink to="/" className="brand-block">
          <p className="brand-overline">Interview Simulator</p>
          <p className="brand-title">Session Atelier</p>
        </NavLink>

        <nav className="app-nav" aria-label="Main navigation">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Home
          </NavLink>
          <NavLink
            to="/interviews/new"
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            Configure
          </NavLink>
          <NavLink
            to="/interviews/history"
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            History
          </NavLink>
        </nav>
      </header>

      <main className="layout-main">
        <Outlet />
      </main>
    </div>
  )
}
