import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import './index.css'
import HomePage from './pages/HomePage'
import InterviewDetailPage from './pages/InterviewDetailPage'
import InterviewHistoryPage from './pages/InterviewHistoryPage'
import InterviewRunPage from './pages/InterviewRunPage'
import InterviewSetupPage from './pages/InterviewSetupPage'
import InterviewSummaryPage from './pages/InterviewSummaryPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<HomePage />} />
          <Route path="interviews/new" element={<InterviewSetupPage />} />
          <Route path="interviews/history" element={<InterviewHistoryPage />} />
          <Route path="interviews/:sessionId/run" element={<InterviewRunPage />} />
          <Route path="interviews/:sessionId/summary" element={<InterviewSummaryPage />} />
          <Route path="interviews/:sessionId/details" element={<InterviewDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
