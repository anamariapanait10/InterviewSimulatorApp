import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './auth'
import './App.css'

const NAV_ITEMS = [
  { to: '/', label: 'Home', match: (pathname: string) => pathname === '/' },
  {
    to: '/interviews/new',
    label: 'Interview',
    match: (pathname: string) => pathname.startsWith('/interviews/new') || pathname.includes('/run'),
  },
  {
    to: '/interviews/history',
    label: 'History',
    match: (pathname: string) =>
      pathname.startsWith('/interviews/history') ||
      pathname.includes('/summary') ||
      pathname.includes('/details'),
  },
  { to: '/companies', label: 'Companies', match: (pathname: string) => pathname.startsWith('/companies') },
] as const

function resolveStageCopy(pathname: string) {
  if (pathname === '/') {
    return {
      kicker: 'Interview Simulator',
      title: 'A clearer view of your practice.',
      description: 'Run mock interviews, review outcomes, and keep the workspace focused on the next action.',
    }
  }
  if (pathname.startsWith('/interviews/new')) {
    return {
      kicker: 'Setup',
      title: 'Configure an interview session',
      description: 'Configure the candidate context, interview format, and coding round before you start.',
    }
  }
  if (pathname.includes('/run')) {
    return {
      kicker: 'Live Session',
      title: 'Interview in progress',
      description: 'Stay focused on the current prompt, your answer, and the active stage.',
    }
  }
  if (pathname.includes('/summary')) {
    return {
      kicker: 'Review',
      title: 'Performance breakdown and feedback',
      description: 'Inspect the final score, narrative feedback, and question-by-question review.',
    }
  }
  if (pathname.includes('/details') || pathname.startsWith('/interviews/history')) {
    return {
      kicker: 'Archive',
      title: 'Saved sessions and past rounds',
      description: 'Browse previous practice sessions and reopen the ones worth revisiting.',
    }
  }
  if (pathname.startsWith('/companies')) {
    return {
      kicker: 'Knowledge Base',
      title: 'Company context and indexed material',
      description: 'Manage saved companies, indexed sources, and retrieval-ready preparation notes.',
    }
  }
  if (pathname.startsWith('/login')) {
    return {
      kicker: 'Access',
      title: 'Sign in to continue practicing',
      description: 'Access saved interviews, dashboard metrics, and company preparation work.',
    }
  }
  if (pathname.startsWith('/register')) {
    return {
      kicker: 'Account',
      title: 'Create your workspace',
      description: 'Create an account to save sessions, track progress, and manage interview prep.',
    }
  }
  return {
    kicker: 'Workspace',
    title: 'Interview simulator',
    description: 'Keep the main workflow visible and the supporting actions close at hand.',
  }
}

export default function App() {
  const location = useLocation()
  const { isAuthenticated, isLoading, user, logout } = useAuth()
  const stageCopy = resolveStageCopy(location.pathname)
  const isHomePage = location.pathname === '/'
  const hasAuthenticatedUser = !isLoading && isAuthenticated && Boolean(user)
  const showGuestAuthActions = !isLoading && !hasAuthenticatedUser && !isHomePage

  return (
    <div className="app-shell">
      <div className="app-frame">
        <aside className="app-sidebar">
          <NavLink to="/" className="brand-block">
            <span className="brand-mark" aria-hidden="true">
              IC
            </span>
            <div className="brand-copy">
              <p className="brand-title">Interview Coach</p>
              <p className="brand-overline">Practice studio</p>
            </div>
          </NavLink>

          <div className="sidebar-nav-section">
            <p className="nav-caption">Main Menu</p>
            <nav className="app-nav" aria-label="Main navigation">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={item.match(location.pathname) ? 'nav-link active' : 'nav-link'}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="sidebar-footer">
            {hasAuthenticatedUser && user ? (
              <div className="sidebar-profile">
                <div className="sidebar-profile-head">
                  <div className="profile-avatar" aria-hidden="true">
                    <span className="profile-avatar-head" />
                    <span className="profile-avatar-body" />
                  </div>
                  <div className="sidebar-profile-copy">
                    <p className="sidebar-profile-label">Signed in</p>
                    <p className="sidebar-profile-email" title={user.email}>
                      {user.email}
                    </p>
                  </div>
                </div>
                <button type="button" className="sidebar-logout" onClick={() => void logout()}>
                  Log Out
                </button>
              </div>
            ) : (
              <p className="sidebar-note">
                Clean practice flows, quieter purple accents, and a lighter reading surface for longer sessions.
              </p>
            )}
          </div>
        </aside>

        <div className="app-stage">
          <header className="stage-header">
            <div className="stage-copy">
              <p className="stage-kicker">{stageCopy.kicker}</p>
              <p className="stage-title">{stageCopy.title}</p>
              <p className="stage-description">{stageCopy.description}</p>
            </div>

            <div className="auth-nav">
              {isHomePage && !isLoading ? (
                <>
                  {hasAuthenticatedUser ? (
                    <>
                      <NavLink to="/interviews/new" className="nav-action nav-action-primary">
                        Open Setup
                      </NavLink>
                      <NavLink to="/interviews/history" className="nav-action">
                        View History
                      </NavLink>
                    </>
                  ) : (
                    <>
                      <NavLink to="/register" className="nav-action nav-action-primary">
                        Register
                      </NavLink>
                      <NavLink to="/login" className="nav-action">
                        Sign In
                      </NavLink>
                    </>
                  )}
                </>
              ) : null}

              {showGuestAuthActions ? (
                <>
                  <NavLink to="/login" className="nav-action">
                    Log In
                  </NavLink>
                  <NavLink to="/register" className="nav-action">
                    Register
                  </NavLink>
                </>
              ) : null}
            </div>
          </header>

          <main className="layout-main">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
