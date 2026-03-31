import { NavLink, Outlet } from 'react-router-dom'
import './App.css'
function HomeWelcome() {
  return (
    <section className="home-welcome">
      <p className="kicker">Practice Smarter</p>
      <h1>Your AI Interview Lab</h1>
      <p>
        Upload your resume, align with a job description, and run realistic mock interviews with coaching
        feedback in real time.
      </p>
      <NavLink to="/coach-chat" className="primary-link">
        Open Coach Chat
      </NavLink>
    </section>
  )
}

function App() {
  return (
    <div className="app-shell">
      <header className="app-nav-wrap">
        <div className="brand-block">
          <p className="brand-overline">Interview Simulator</p>
          <p className="brand-title">Career Craft Studio</p>
        </div>
        <nav className="app-nav" aria-label="Main navigation">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Home
          </NavLink>
          <NavLink
            to="/coach-chat"
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            Coach Chat
          </NavLink>
        </nav>
      </header>

      <main className="layout-main">
        <Outlet />
      </main>
    </div>
  )
}

export { HomeWelcome }

export default App
