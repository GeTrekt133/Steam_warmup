import {
  Layers,
  Radio,
  Hammer,
  BadgeCheck,
  Gem,
  Target,
  Flame,
  CircuitBoard,
  ArrowRight,
  FileInput,
  Orbit,
  ShieldHalf,
  Coins,
  Antenna,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Link } from 'react-router-dom'
import { getCurrentUser } from '@/lib/auth'

// ─── Загрузка данных из localStorage ─────────────────────────

function getAccountStats() {
  try {
    const raw = localStorage.getItem('steam_accounts')
    if (!raw) return { total: 0, with2fa: 0, farmed: 0, dropCollected: 0, dropValue: 0, farming: 0, online: 0 }
    const accounts = JSON.parse(raw) as {
      maFile?: boolean
      isFarmed?: boolean
      isDropCollected?: boolean
      dropValue?: number
      status?: string
    }[]
    return {
      total: accounts.length,
      with2fa: accounts.filter((a) => a.maFile).length,
      farmed: accounts.filter((a) => a.isFarmed).length,
      dropCollected: accounts.filter((a) => a.isDropCollected).length,
      dropValue: accounts.reduce((sum, a) => sum + (a.dropValue ?? 0), 0),
      farming: accounts.filter((a) => a.status === 'farming').length,
      online: accounts.filter((a) => a.status && a.status !== 'waiting').length,
    }
  } catch {
    return { total: 0, with2fa: 0, farmed: 0, dropCollected: 0, dropValue: 0, farming: 0, online: 0 }
  }
}

// ─── Горизонтальный прогресс-бар ─────────────────────────────

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(value / max, 1) * 100 : 0
  return (
    <div className="h-1.5 rounded-full bg-[hsl(var(--border))] overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  )
}

// ─── Главная ─────────────────────────────────────────────────

export function DashboardPage() {
  const s = getAccountStats()
  const user = getCurrentUser()
  const pctFarmed = s.total > 0 ? Math.round((s.farmed / s.total) * 100) : 0

  return (
    <div className="p-6 space-y-4">

      {/* ═══ Баннер-приветствие ═══ */}
      <div className="relative overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
        {/* Декоративный градиент */}
        <div className="absolute top-0 right-0 w-48 h-48 rounded-full bg-[hsl(var(--primary)/0.08)] blur-3xl -translate-y-1/2 translate-x-1/4 pointer-events-none" />
        <div className="relative flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">
              {user ? `Привет, ${user}` : 'Командный центр'}
            </h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">
              {s.total === 0
                ? 'Добавьте первые аккаунты, чтобы начать работу'
                : `${s.total} аккаунтов · ${s.online} онлайн · ${pctFarmed}% зафармлено`}
            </p>
          </div>
          {s.total === 0 && (
            <Link
              to="/accounts"
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-sm font-medium hover:opacity-90 transition-opacity"
            >
              <FileInput className="h-4 w-4" />
              Импорт
            </Link>
          )}
        </div>
      </div>

      {/* ═══ Бенто-сетка: 3 колонки ═══ */}
      <div className="grid grid-cols-3 gap-4">

        {/* ── Карточка: Аккаунты (большая, span 1) ── */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-violet-500/15">
                <Layers className="h-4 w-4 text-violet-400" />
              </div>
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wider">Аккаунты</span>
            </div>
            <span className="text-2xl font-bold">{s.total}</span>
          </div>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-[11px] text-[hsl(var(--muted-foreground))] mb-1">
                <span>С 2FA</span>
                <span>{s.with2fa} / {s.total}</span>
              </div>
              <ProgressBar value={s.with2fa} max={Math.max(s.total, 1)} color="#a78bfa" />
            </div>
            <div>
              <div className="flex justify-between text-[11px] text-[hsl(var(--muted-foreground))] mb-1">
                <span>Онлайн</span>
                <span>{s.online} / {s.total}</span>
              </div>
              <ProgressBar value={s.online} max={Math.max(s.total, 1)} color="#34d399" />
            </div>
          </div>
        </div>

        {/* ── Карточка: Фарм прогресс (большая, span 1) ── */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-blue-500/15">
                <Hammer className="h-4 w-4 text-blue-400" />
              </div>
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wider">Фарм</span>
            </div>
            <div className="text-right">
              <span className="text-2xl font-bold">{pctFarmed}%</span>
            </div>
          </div>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-[11px] text-[hsl(var(--muted-foreground))] mb-1">
                <span>Зафармлено</span>
                <span>{s.farmed} / {s.total}</span>
              </div>
              <ProgressBar value={s.farmed} max={Math.max(s.total, 1)} color="hsl(var(--primary))" />
            </div>
            <div>
              <div className="flex justify-between text-[11px] text-[hsl(var(--muted-foreground))] mb-1">
                <span>Фармят сейчас</span>
                <span>{s.farming}</span>
              </div>
              <ProgressBar value={s.farming} max={Math.max(s.total, 1)} color="#60a5fa" />
            </div>
          </div>
        </div>

        {/* ── Карточка: Дропы (большая, span 1) ── */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 flex flex-col justify-between">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-emerald-500/15">
                <Gem className="h-4 w-4 text-emerald-400" />
              </div>
              <span className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wider">Дропы</span>
            </div>
            <span className="text-2xl font-bold">{s.dropCollected}</span>
          </div>
          <div className="space-y-3">
            <div>
              <div className="flex justify-between text-[11px] text-[hsl(var(--muted-foreground))] mb-1">
                <span>Собрано</span>
                <span>{s.dropCollected} / {s.total}</span>
              </div>
              <ProgressBar value={s.dropCollected} max={Math.max(s.total, 1)} color="#34d399" />
            </div>
            <div className="flex items-center justify-between pt-1 border-t border-[hsl(var(--border))]">
              <span className="text-[11px] text-[hsl(var(--muted-foreground))]">Сумма дропов</span>
              <span className="text-sm font-semibold text-emerald-400">${s.dropValue.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ Мини-статы (горизонтальная полоса) ═══ */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Онлайн', value: s.online, icon: Antenna, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
          { label: 'Фармят', value: s.farming, icon: Orbit, color: 'text-blue-400', bg: 'bg-blue-500/10' },
          { label: 'С 2FA', value: s.with2fa, icon: ShieldHalf, color: 'text-amber-400', bg: 'bg-amber-500/10' },
          { label: 'Заработано', value: `$${s.dropValue.toFixed(2)}`, icon: Coins, color: 'text-teal-400', bg: 'bg-teal-500/10' },
        ].map((m) => (
          <div key={m.label} className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-3">
            <div className={cn('p-1.5 rounded-md', m.bg)}>
              <m.icon className={cn('h-3.5 w-3.5', m.color)} />
            </div>
            <div>
              <div className="text-[10px] text-[hsl(var(--muted-foreground))] uppercase tracking-wider">{m.label}</div>
              <div className="text-sm font-bold leading-tight">{m.value}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ═══ Быстрые действия + Активность ═══ */}
      <div className="grid grid-cols-[1fr_340px] gap-4">

        {/* Быстрые действия — вертикальный список */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <span className="text-xs font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-4 block">Быстрые действия</span>
          <div className="flex flex-col gap-2">
            {[
              { label: 'Импорт аккаунтов', desc: 'Загрузить TXT или maFile', to: '/accounts', icon: FileInput, accent: 'group-hover:text-violet-400', iconBg: 'bg-violet-500/15' },
              { label: 'Запустить фарм', desc: 'Начать фарм аккаунтов', to: '/farm', icon: Target, accent: 'group-hover:text-blue-400', iconBg: 'bg-blue-500/15' },
              { label: 'Прогрев бейджей', desc: 'Community Leader badge', to: '/warmup', icon: Flame, accent: 'group-hover:text-orange-400', iconBg: 'bg-orange-500/15' },
              { label: 'Управление ботами', desc: 'ArchiSteamFarm', to: '/bots', icon: CircuitBoard, accent: 'group-hover:text-emerald-400', iconBg: 'bg-emerald-500/15' },
            ].map((a) => (
              <Link
                key={a.to}
                to={a.to}
                className="group flex items-center gap-4 rounded-lg border border-[hsl(var(--border))] px-5 py-4 hover:bg-[hsl(var(--accent))] hover:border-[hsl(var(--primary)/0.3)] transition-colors"
              >
                <div className={cn('p-2.5 rounded-lg', a.iconBg)}>
                  <a.icon className={cn('h-5 w-5 text-[hsl(var(--muted-foreground))] transition-colors', a.accent)} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{a.label}</div>
                  <div className="text-xs text-[hsl(var(--muted-foreground))]">{a.desc}</div>
                </div>
                <ArrowRight className="h-4 w-4 text-[hsl(var(--muted-foreground))] opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
              </Link>
            ))}
          </div>
        </div>

        {/* Активность — таймлайн */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <span className="text-xs font-semibold text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-4 block">Активность</span>

          {s.total === 0 ? (
            <div className="text-center py-6">
              <Layers className="h-7 w-7 mx-auto mb-2 text-[hsl(var(--muted-foreground))] opacity-30" />
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Пока нет данных
              </p>
            </div>
          ) : (
            <div className="relative pl-5 space-y-4">
              {/* Вертикальная линия таймлайна */}
              <div className="absolute left-[7px] top-1 bottom-1 w-px bg-[hsl(var(--border))]" />

              {s.farming > 0 && (
                <TimelineItem
                  dotColor="bg-blue-400"
                  icon={Orbit}
                  text={`${s.farming} аккаунтов фармят`}
                  detail="прямо сейчас"
                />
              )}
              {s.farmed > 0 && (
                <TimelineItem
                  dotColor="bg-amber-400"
                  icon={BadgeCheck}
                  text={`${s.farmed} зафармлены`}
                  detail={`из ${s.total} аккаунтов`}
                />
              )}
              {s.dropCollected > 0 && (
                <TimelineItem
                  dotColor="bg-emerald-400"
                  icon={Gem}
                  text={`${s.dropCollected} дропов`}
                  detail={`на $${s.dropValue.toFixed(2)}`}
                />
              )}
              {s.online > 0 && (
                <TimelineItem
                  dotColor="bg-green-400"
                  icon={Radio}
                  text={`${s.online} онлайн`}
                  detail="активны"
                />
              )}
              {s.farmed === 0 && s.farming === 0 && s.dropCollected === 0 && (
                <TimelineItem
                  dotColor="bg-[hsl(var(--muted-foreground))]"
                  icon={Orbit}
                  text="Ожидание"
                  detail="ни один аккаунт ещё не фармил"
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Вспомогательные компоненты ──────────────────────────────

function TimelineItem({ dotColor, icon: Icon, text, detail }: {
  dotColor: string; icon: React.ElementType; text: string; detail: string
}) {
  return (
    <div className="relative flex items-start gap-3">
      {/* Точка таймлайна */}
      <div className={cn('absolute -left-5 top-1 h-[9px] w-[9px] rounded-full ring-2 ring-[hsl(var(--card))]', dotColor)} />
      <Icon className="h-3.5 w-3.5 mt-0.5 text-[hsl(var(--muted-foreground))] flex-shrink-0" />
      <div>
        <span className="text-sm font-medium">{text}</span>
        <span className="text-xs text-[hsl(var(--muted-foreground))] ml-1.5">{detail}</span>
      </div>
    </div>
  )
}
