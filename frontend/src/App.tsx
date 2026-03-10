import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { MainLayout } from '@/components/layout/MainLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { AccountsPage } from '@/pages/AccountsPage'
import { ProxiesPage } from '@/pages/ProxiesPage'
import { RegistrationPage } from '@/pages/RegistrationPage'
import { BotsPage } from '@/pages/BotsPage'
import { WarmupPage } from '@/pages/WarmupPage'
import { FarmingPage } from '@/pages/FarmingPage'
import { MarketplacePage } from '@/pages/MarketplacePage'
import { SettingsPage } from '@/pages/SettingsPage'
import { LoginPage } from '@/pages/LoginPage'
import { RegisterPage } from '@/pages/RegisterPage'

/**
 * Auth guard — если нет JWT токена, редиректим на логин.
 * HashRouter используется потому что Electron грузит файлы через file://,
 * а BrowserRouter требует серверного роутинга.
 */
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('auth_token')
  if (!token) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function App() {
  return (
    <HashRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        {/* Protected routes with sidebar layout */}
        <Route
          element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/proxies" element={<ProxiesPage />} />
          <Route path="/registration" element={<RegistrationPage />} />
          <Route path="/bots" element={<BotsPage />} />
          <Route path="/warmup" element={<WarmupPage />} />
          <Route path="/farming" element={<FarmingPage />} />
          <Route path="/marketplace" element={<MarketplacePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  )
}

export default App
