import { NavLink, useNavigate } from 'react-router-dom'
import {
  Gauge,
  Swords,
  ContactRound,
  Waypoints,
  Fingerprint,
  CircuitBoard,
  Sparkles,
  Hourglass,
  Store,
  SlidersHorizontal,
  LogOut,
  User,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { logoutUser, getCurrentUser } from '@/lib/auth'

const navItems = [
  { path: '/', label: 'Главная', icon: Gauge },
  { path: '/farm', label: 'Фарм', icon: Swords },
  { path: '/accounts', label: 'Аккаунты', icon: ContactRound },
  { path: '/proxies', label: 'Прокси', icon: Waypoints },
  { path: '/registration', label: 'Регистрация', icon: Fingerprint },
  { path: '/bots', label: 'ASF Боты', icon: CircuitBoard },
  { path: '/warmup', label: 'Прогрев', icon: Sparkles },
  { path: '/farming', label: 'Фарм часов', icon: Hourglass },
  { path: '/marketplace', label: 'Маркетплейс', icon: Store },
  { path: '/settings', label: 'Настройки', icon: SlidersHorizontal },
]

export function Sidebar() {
  const navigate = useNavigate()
  const currentUser = getCurrentUser()

  function handleLogout() {
    logoutUser()
    navigate('/login')
  }

  return (
    <aside className="fixed left-0 top-0 h-screen w-[250px] border-r border-[hsl(var(--border))] bg-[hsl(var(--sidebar-background))] flex flex-col">
      {/* Logo */}
      <div className="px-5 py-4 border-b border-[hsl(var(--sidebar-border))]">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-zinc-900 flex items-center justify-center text-base">
            👨🏿
          </div>
          <div>
            <div className="text-sm font-bold text-[hsl(var(--sidebar-foreground))]">
              Selik где деньги
            </div>
            <div className="text-[10px] text-[hsl(var(--muted-foreground))]">
              v0.1.0
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                isActive
                  ? 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]'
                  : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--sidebar-accent))] hover:text-[hsl(var(--sidebar-foreground))]'
              )
            }
          >
            <item.icon className="h-4 w-4 flex-shrink-0" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* User & Logout */}
      <div className="px-3 py-3 border-t border-[hsl(var(--sidebar-border))]">
        {currentUser && (
          <div className="flex items-center gap-2 px-3 py-1.5 mb-2">
            <User className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
            <span className="text-sm text-[hsl(var(--sidebar-foreground))] truncate">{currentUser}</span>
          </div>
        )}
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium w-full text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--destructive)/0.15)] hover:text-[hsl(var(--destructive-foreground))] transition-colors"
        >
          <LogOut className="h-4 w-4 flex-shrink-0" />
          Выйти
        </button>
      </div>
    </aside>
  )
}
