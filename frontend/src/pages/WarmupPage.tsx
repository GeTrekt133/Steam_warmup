import { useState, useEffect, useCallback, useRef } from 'react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  Sparkles,
  Play,
  Square,
  Users,
  CheckCircle,
  AlertCircle,
  Clock,
  Loader2,
  RefreshCw,
  SkipForward,
  Timer,
  RotateCcw,
  Download,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Типы ────────────────────────────────────────────────────

interface Quest {
  id: string
  name: string
}

interface QuestStatus {
  id: string
  name: string
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped'
  error: string | null
  retries: number
}

interface AccountStatus {
  login: string
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped'
  quests_done: number
  quests_total: number
  current_quest: string | null
  error: string | null
  quests: QuestStatus[]
}

interface WarmupTask {
  task_id: string
  total: number
  completed: number
  running: boolean
  accounts: AccountStatus[]
}

interface LocalAccount {
  id: string
  login: string
  password: string
  sharedSecret?: string
  maFile: boolean
}

// ─── Компонент ───────────────────────────────────────────────

export function WarmupPage() {
  const [accounts, setAccounts] = useState<LocalAccount[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const [availableQuests, setAvailableQuests] = useState<Quest[]>([])
  const [selectedQuests, setSelectedQuests] = useState<Set<string>>(new Set(['all']))

  const [masterSteamId, setMasterSteamId] = useState('')
  const [maxConcurrent, setMaxConcurrent] = useState(2)
  const [textPrompt, setTextPrompt] = useState('')

  const [warmupTimeout, setWarmupTimeout] = useState(600)
  const [maxQuestRetries, setMaxQuestRetries] = useState(3)

  const [taskId, setTaskId] = useState<string | null>(null)
  const [task, setTask] = useState<WarmupTask | null>(null)
  const [startLoading, setStartLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ─── Загрузка ─────────────────────────────────────────────

  useEffect(() => {
    // Загрузить аккаунты из localStorage (содержат пароли/секреты)
    try {
      const raw = localStorage.getItem('steam_accounts')
      setAccounts(raw ? JSON.parse(raw) : [])
    } catch {
      setAccounts([])
    }
    api.get('/api/warmup/quests').then((res) => {
      setAvailableQuests(res.data.quests ?? [])
    }).catch(() => {})
  }, [])

  // ─── Polling ──────────────────────────────────────────────

  const startPolling = useCallback((tid: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const res = await api.get(`/api/warmup/status/${tid}`)
        setTask(res.data)
        if (!res.data.running) {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
      }
    }, 3000)
  }, [])

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  // ─── Действия ─────────────────────────────────────────────

  function toggleAccount(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  function selectAll() {
    if (selectedIds.size === accounts.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(accounts.map((a) => a.id)))
  }

  function toggleQuest(id: string) {
    setSelectedQuests((prev) => {
      if (id === 'all') return new Set(['all'])
      const next = new Set(prev)
      next.delete('all')
      if (next.has(id)) next.delete(id); else next.add(id)
      return next.size === 0 ? new Set(['all']) : next
    })
  }

  async function handleStart() {
    const selected = accounts.filter((a) => selectedIds.has(a.id))
    if (selected.length === 0) { alert('Выберите аккаунты'); return }

    setStartLoading(true)
    try {
      const res = await api.post('/api/warmup/start', {
        accounts: selected.map((a) => ({
          login: a.login,
          password: a.password,
          shared_secret: a.sharedSecret || undefined,
        })),
        master_steam_id: masterSteamId || undefined,
        quests: Array.from(selectedQuests),
        max_concurrent: maxConcurrent,
        text_prompt: textPrompt || undefined,
        warmup_timeout: warmupTimeout,
        max_quest_retries: maxQuestRetries,
      })
      setTaskId(res.data.task_id)
      setTask(null)
      startPolling(res.data.task_id)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setStartLoading(false)
    }
  }

  async function handleStop() {
    if (taskId) await api.post(`/api/warmup/stop/${taskId}`).catch(() => {})
  }

  // ─── Рендер ───────────────────────────────────────────────

  const isRunning = task?.running ?? false

  return (
    <div className="flex h-full flex-col gap-6 p-6">
      <div className="flex items-center gap-3">
        <Sparkles className="h-6 w-6 text-[hsl(var(--primary))]" />
        <h1 className="text-2xl font-bold">Прогрев аккаунтов</h1>
        <span className="text-sm text-[hsl(var(--muted-foreground))]">Community Badge</span>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_350px]">
        {/* Левая колонка */}
        <div className="flex flex-col gap-4">
          {/* Аккаунты */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 font-semibold">
                <Users className="h-4 w-4" /> Аккаунты ({accounts.length})
              </h2>
              <button onClick={selectAll} className="text-xs text-[hsl(var(--primary))] hover:underline">
                {selectedIds.size === accounts.length && accounts.length > 0 ? 'Снять всё' : 'Выбрать всех'}
              </button>
            </div>
            {accounts.length === 0 ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">Нет аккаунтов</p>
            ) : (
              <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 max-h-48 overflow-y-auto">
                {accounts.map((acc) => (
                  <label key={acc.id} className={cn(
                    'flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                    selectedIds.has(acc.id) ? 'bg-[hsl(var(--primary)/0.15)]' : 'hover:bg-[hsl(var(--accent))]'
                  )}>
                    <input type="checkbox" checked={selectedIds.has(acc.id)} onChange={() => toggleAccount(acc.id)} className="h-3.5 w-3.5 accent-[hsl(var(--primary))]" />
                    <span className="truncate font-mono">{acc.login}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* Мастер */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-2 font-semibold">Мастер-аккаунт</h2>
            <p className="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
              Steam ID для квестов «добавить друга» и «комментарий». Профиль должен быть открытым.
            </p>
            <input
              value={masterSteamId} onChange={(e) => setMasterSteamId(e.target.value)}
              placeholder="76561198..."
              className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
            />
          </div>

          {/* AI-генерация текстов */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-2 font-semibold">AI-генерация текстов</h2>
            <p className="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
              Промпт для LLM (Groq/Gemini) — стиль никнеймов, описаний, отзывов. Пусто = случайные из списка.
            </p>
            <input
              value={textPrompt} onChange={(e) => setTextPrompt(e.target.value)}
              placeholder="Например: military themed, aggressive tone, Russian style..."
              className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
            />
            <p className="mt-1 text-[10px] text-[hsl(var(--muted-foreground))]">
              Требуется GROQ_API_KEY или GEMINI_API_KEY в .env. Без ключа — fallback на хардкод-списки.
            </p>
          </div>

          {/* Квесты */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-3 font-semibold">Квесты</h2>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => toggleQuest('all')} className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                selectedQuests.has('all') ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
              )}>Все квесты</button>
              {availableQuests.map((q) => (
                <button key={q.id} onClick={() => toggleQuest(q.id)} className={cn(
                  'rounded-md px-3 py-1.5 text-xs transition-colors',
                  selectedQuests.has(q.id) ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
                )}>{q.name}</button>
              ))}
            </div>
          </div>

          {/* Параллельность */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-2 font-semibold">Параллельность</h2>
            <div className="flex items-center gap-3">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} onClick={() => setMaxConcurrent(n)} className={cn(
                  'h-8 w-8 rounded-md text-sm font-medium transition-colors',
                  maxConcurrent === n ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
                )}>{n}</button>
              ))}
              <span className="text-xs text-[hsl(var(--muted-foreground))]">браузеров одновременно</span>
            </div>
          </div>

          {/* Настройки антибана */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-3 font-semibold">Настройки надёжности</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">
                  <Timer className="mr-1 inline h-3 w-3" />
                  Timeout на аккаунт (сек)
                </label>
                <input
                  type="number" min={60} max={3600} value={warmupTimeout}
                  onChange={(e) => setWarmupTimeout(Number(e.target.value))}
                  className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                />
                <span className="text-[10px] text-[hsl(var(--muted-foreground))]">{Math.floor(warmupTimeout / 60)} мин</span>
              </div>
              <div>
                <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">
                  <RotateCcw className="mr-1 inline h-3 w-3" />
                  Макс. retry на квест
                </label>
                <div className="flex items-center gap-2">
                  {[1, 2, 3, 5].map((n) => (
                    <button key={n} onClick={() => setMaxQuestRetries(n)} className={cn(
                      'h-8 w-8 rounded-md text-sm font-medium transition-colors',
                      maxQuestRetries === n ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
                    )}>{n}</button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Кнопки */}
          <div className="flex gap-3">
            <Button size="lg" className="flex-1" loading={startLoading} disabled={selectedIds.size === 0 || isRunning} onClick={handleStart}>
              <Sparkles className="h-4 w-4" /> Запустить прогрев ({selectedIds.size} акк.)
            </Button>
            {isRunning && (
              <Button variant="destructive" size="lg" onClick={handleStop}>
                <Square className="h-4 w-4" /> Стоп
              </Button>
            )}
          </div>
        </div>

        {/* Правая колонка: прогресс */}
        <div className="flex flex-col gap-4">
          {task ? (
            <>
              <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span className="font-medium">{task.running ? 'Прогрев...' : 'Завершён'}</span>
                  <span className="text-[hsl(var(--muted-foreground))]">{task.completed}/{task.total}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                  <div className="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-500"
                    style={{ width: `${task.total > 0 ? (task.completed / task.total) * 100 : 0}%` }} />
                </div>
              </div>

              {task.accounts.map((acc) => (
                <div key={acc.login} className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-mono text-sm font-medium">{acc.login}</span>
                    <StatusBadge status={acc.status} />
                  </div>
                  {acc.current_quest && (
                    <p className="mb-2 flex items-center gap-1.5 text-xs text-[hsl(var(--primary))]">
                      <Loader2 className="h-3 w-3 animate-spin" /> {acc.current_quest}
                    </p>
                  )}
                  {acc.error && <p className="mb-2 text-xs text-[hsl(var(--destructive))]">{acc.error}</p>}
                  <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                    <div className="h-full rounded-full bg-[hsl(var(--primary))] transition-all"
                      style={{ width: `${acc.quests_total > 0 ? (acc.quests_done / acc.quests_total) * 100 : 0}%` }} />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {acc.quests.map((q) => (
                      <span key={q.id} title={q.error ? `${q.name}: ${q.error}` : q.name} className={cn(
                        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px]',
                        q.status === 'done' && 'bg-green-500/20 text-green-400',
                        q.status === 'running' && 'bg-blue-500/20 text-blue-400',
                        q.status === 'error' && 'bg-red-500/20 text-red-400',
                        q.status === 'skipped' && 'bg-yellow-500/20 text-yellow-400',
                        q.status === 'pending' && 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]',
                      )}>
                        {q.status === 'skipped' && <SkipForward className="h-2.5 w-2.5" />}
                        {q.name}
                        {q.retries > 0 && (
                          <span className="ml-0.5 flex items-center gap-0.5 opacity-75">
                            <RotateCcw className="h-2 w-2" />{q.retries}
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-[hsl(var(--border-strong))] p-8 text-center">
              <Sparkles className="mx-auto mb-3 h-10 w-10 text-[hsl(var(--muted-foreground))]" />
              <p className="mb-1 font-medium">Запустите прогрев</p>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Выберите аккаунты, укажите мастер-аккаунт и нажмите «Запустить»
              </p>
            </div>
          )}

          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 text-xs text-[hsl(var(--muted-foreground))]">
            <p className="mb-2 font-medium text-[hsl(var(--foreground))]">Как работает</p>
            <ul className="space-y-1">
              <li>• Для каждого аккаунта открывается браузер Playwright</li>
              <li>• Автологин через shared_secret (2FA)</li>
              <li>• Квесты выполняются группами с рандомными паузами</li>
              <li>• При ошибке — автоматический retry (до {maxQuestRetries}x)</li>
              <li>• Мастер-аккаунт нужен для комментариев и друзей</li>
              <li>• Timeout: {Math.floor(warmupTimeout / 60)} мин на аккаунт</li>
              <li>• Human-like задержки и действия (антибан)</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'done') return <span className="inline-flex items-center gap-1 rounded-full bg-green-500/20 px-2 py-0.5 text-xs text-green-400"><CheckCircle className="h-3 w-3" /> Готово</span>
  if (status === 'running') return <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/20 px-2 py-0.5 text-xs text-blue-400"><Loader2 className="h-3 w-3 animate-spin" /> Выполняется</span>
  if (status === 'error') return <span className="inline-flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-xs text-red-400"><AlertCircle className="h-3 w-3" /> Ошибка</span>
  if (status === 'skipped') return <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs text-yellow-400"><SkipForward className="h-3 w-3" /> Пропущен</span>
  return <span className="inline-flex items-center gap-1 rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-xs text-[hsl(var(--muted-foreground))]"><Clock className="h-3 w-3" /> Ожидание</span>
}
