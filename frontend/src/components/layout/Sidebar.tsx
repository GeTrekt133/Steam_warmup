import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Users,
  Globe,
  UserPlus,
  Bot,
  Flame,
  Clock,
  ShoppingCart,
  Settings,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/', label: 'Главная', icon: LayoutDashboard },
  { path: '/accounts', label: 'Аккаунты', icon: Users },
  { path: '/proxies', label: 'Прокси', icon: Globe },
  { path: '/registration', label: 'Регистрация', icon: UserPlus },
  { path: '/bots', label: 'ASF Боты', icon: Bot },
  { path: '/warmup', label: 'Прогрев', icon: Flame },
  { path: '/farming', label: 'Фарм часов', icon: Clock },
  { path: '/marketplace', label: 'Маркетплейс', icon: ShoppingCart },
  { path: '/settings', label: 'Настройки', icon: Settings },
]

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-[250px] border-r border-[hsl(var(--border))] bg-[hsl(var(--sidebar-background))] flex flex-col">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[hsl(var(--sidebar-border))]">
        <div className="text-sm font-bold text-[hsl(var(--sidebar-foreground))]">
          Steam Farming Panel
        </div>
        <div className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
          v0.1.0
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-3 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-[hsl(var(--sidebar-accent))] text-[hsl(var(--sidebar-accent-foreground))]'
                  : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--sidebar-accent))] hover:text-[hsl(var(--sidebar-accent-foreground))]'
              )
            }
          >
            <item.icon className="h-4 w-4 flex-shrink-0" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-[hsl(var(--sidebar-border))] text-xs text-[hsl(var(--muted-foreground))]">
        Phase 0 — Фундамент
      </div>
    </aside>
  )
}
