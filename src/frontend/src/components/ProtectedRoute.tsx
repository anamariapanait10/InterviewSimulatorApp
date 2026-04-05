import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'
import '../pages/InterviewFlow.css'

export default function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <section className="flow-card">
        <p className="section-eyebrow">Authentication</p>
        <h1>Loading account...</h1>
      </section>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
