import { useState, useEffect, useRef, useCallback } from 'react'
import api from '@/lib/api'
import {
  UserPlus, Play, Square, RefreshCw, Trash2, X,
  CheckCircle, XCircle, Clock, Loader2, ChevronDown, ChevronUp,
} from 'lucide-react'

interface StepStatus {
  step: string
  status: string
  detail: string | null
}

interface RegResult {
  success: boolean
  login: string | null
  password: string | null
  email: string | null
  steam_id: string | null
  account_id: number | null
  error: string | null
  steps: StepStatus[]
}

interface BatchStatus {
  task_id: string
  total: number
  completed: number
  succeeded: number
  failed: number
  in_progress: number
  results: RegResult[]
}

interface SolverInfo {
  available: string[]
  stats: Record<string, any>
}

type Mode = 'single' | 'batch'

const STEP_NAMES: Record<string, string> = {
  captcha_init: 'Captcha GID',
  captcha_solve: 'Решение капчи',
  email_verify: 'Отправка email',
  email_fetch: 'Ожидание письма',
  email_confirm: 'Подтверждение',
  create_account: 'Создание аккаунта',
}

function StepIcon({ status }: { status: string }) {
  if (status === 'done') return <CheckCircle size={14} className="text-green-400" />
  if (status === 'error') return <XCircle size={14} className="text-red-400" />
  if (status === 'running') return <Loader2 size={14} className="text-blue-400 animate-spin" />
  return <Clock size={14} className="text-[hsl(var(--muted-foreground))]" />
}

export function RegistrationPage() {
  const [mode, setMode] = useState<Mode>('single')
  const [solvers, setSolvers] = useState<SolverInfo | null>(null)

  // Single mode
  const [email, setEmail] = useState('')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [proxyId, setProxyId] = useState('')
  const [groupId, setGroupId] = useState('')
  const [singleLoading, setSingleLoading] = useState(false)
  const [singleResult, setSingleResult] = useState<RegResult | null>(null)

  // Batch mode
  const [emails, setEmails] = useState('')
  const [loginPrefix, setLoginPrefix] = useState('')
  const [maxConcurrent, setMaxConcurrent] = useState('3')
  const [batchTaskId, setBatchTaskId] = useState<string | null>(null)
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [batchPolling, setBatchPolling] = useState(false)

  // Logs
  const [results, setResults] = useState<RegResult[]>([])
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const [message, setMessage] = useState<{ text: string; type: 'ok' | 'err' } | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMessage({ text, type })
    setTimeout(() => setMessage(null), 4000)
  }

  // Load solvers info
  useEffect(() => {
    api.get('/api/captcha/solvers').then(r => setSolvers(r.data)).catch(() => {})
  }, [])

  // Batch polling
  const startPolling = useCallback((taskId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    setBatchPolling(true)
    pollRef.current = setInterval(async () => {
      try {
        const r = await api.get(`/api/register/status/${taskId}`)
        setBatchStatus(r.data)
        if (r.data.completed >= r.data.total) {
          clearInterval(pollRef.current!)
          pollRef.current = null
          setBatchPolling(false)
          setResults(prev => [...prev, ...r.data.results])
          flash(`Готово: ${r.data.succeeded} успешно, ${r.data.failed} ошибок`)
        }
      } catch {
        clearInterval(pollRef.current!)
        pollRef.current = null
        setBatchPolling(false)
      }
    }, 3000)
  }, [])

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const handleSingle = async () => {
    if (!email) return
    setSingleLoading(true)
    setSingleResult(null)
    try {
      const r = await api.post('/api/register/single', {
        email,
        login: login || undefined,
        password: password || undefined,
        proxy_id: proxyId ? parseInt(proxyId) : undefined,
        group_id: groupId ? parseInt(groupId) : undefined,
      }, { timeout: 120000 })
      setSingleResult(r.data)
      setResults(prev => [r.data, ...prev])
      if (r.data.success) {
        flash(`Аккаунт создан: ${r.data.login}`)
      } else {
        flash(r.data.error || 'Ошибка регистрации', 'err')
      }
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка запроса', 'err')
    } finally {
      setSingleLoading(false)
    }
  }

  const handleBatch = async () => {
    const emailList = emails.split('\n').map(l => l.trim()).filter(Boolean)
    if (!emailList.length) return
    try {
      const r = await api.post('/api/register/batch', {
        emails: emailList,
        login_prefix: loginPrefix || undefined,
        max_concurrent: parseInt(maxConcurrent) || 3,
        group_id: groupId ? parseInt(groupId) : undefined,
      })
      setBatchTaskId(r.data.task_id)
      setBatchStatus(null)
      startPolling(r.data.task_id)
      flash(`Запущено: ${r.data.total} аккаунтов (task: ${r.data.task_id})`)
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка запуска', 'err')
    }
  }

  const noSolvers = solvers && solvers.available.length === 0

  return (
    <div className="p-6 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <UserPlus size={24} />
          <h1 className="text-2xl font-bold">Регистрация</h1>
        </div>
        <div className="flex items-center gap-2">
          {solvers && (
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              Солверы: {solvers.available.length > 0
                ? solvers.available.join(', ')
                : 'нет (добавьте API ключи в .env)'}
            </span>
          )}
        </div>
      </div>

      {/* Warning if no solvers */}
      {noSolvers && (
        <div className="mb-4 px-4 py-3 rounded bg-yellow-500/20 text-yellow-400 text-sm">
          Нет доступных captcha-солверов. Добавьте GROQ_API_KEY или GEMINI_API_KEY в .env файл бэкенда.
        </div>
      )}

      {/* Message */}
      {message && (
        <div className={`mb-3 px-4 py-2 rounded text-sm ${message.type === 'ok' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
          {message.text}
        </div>
      )}

      <div className="flex gap-4 flex-1 min-h-0">
        {/* Left: Form */}
        <div className="w-96 flex-shrink-0 flex flex-col gap-4">
          {/* Mode tabs */}
          <div className="flex rounded-lg border border-[hsl(var(--border))] overflow-hidden">
            <button
              onClick={() => setMode('single')}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${mode === 'single' ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'bg-[hsl(var(--card))]'}`}
            >
              Одиночная
            </button>
            <button
              onClick={() => setMode('batch')}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${mode === 'batch' ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'bg-[hsl(var(--card))]'}`}
            >
              Массовая
            </button>
          </div>

          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 flex flex-col gap-3">
            {mode === 'single' ? (
              <>
                <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Email:пароль</label>
                <input
                  className="input w-full"
                  placeholder="user@mail.ru:emailpass123"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                />
                <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Steam логин (опц.)</label>
                <input
                  className="input w-full"
                  placeholder="Авто-генерация если пусто"
                  value={login}
                  onChange={e => setLogin(e.target.value)}
                />
                <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Steam пароль (опц.)</label>
                <input
                  className="input w-full"
                  placeholder="Авто-генерация если пусто"
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                />
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Proxy ID</label>
                    <input className="input w-full mt-1" placeholder="—" value={proxyId} onChange={e => setProxyId(e.target.value)} />
                  </div>
                  <div className="flex-1">
                    <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Группа ID</label>
                    <input className="input w-full mt-1" placeholder="—" value={groupId} onChange={e => setGroupId(e.target.value)} />
                  </div>
                </div>
                <button
                  onClick={handleSingle}
                  disabled={singleLoading || !email || noSolvers}
                  className="btn-primary w-full mt-2"
                >
                  {singleLoading ? (
                    <><Loader2 size={16} className="animate-spin" /> Регистрация...</>
                  ) : (
                    <><Play size={16} /> Зарегистрировать</>
                  )}
                </button>
              </>
            ) : (
              <>
                <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">
                  Email-ы (email:password, по строке)
                </label>
                <textarea
                  className="input w-full h-40 resize-none font-mono text-xs"
                  placeholder={"user1@mail.ru:pass1\nuser2@gmail.com:pass2\nuser3@yandex.ru:pass3"}
                  value={emails}
                  onChange={e => setEmails(e.target.value)}
                />
                <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Префикс логинов (опц.)</label>
                <input
                  className="input w-full"
                  placeholder="farm → farm_001, farm_002..."
                  value={loginPrefix}
                  onChange={e => setLoginPrefix(e.target.value)}
                />
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Параллельно</label>
                    <input
                      className="input w-full mt-1"
                      type="number" min="1" max="10"
                      value={maxConcurrent}
                      onChange={e => setMaxConcurrent(e.target.value)}
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide">Группа ID</label>
                    <input className="input w-full mt-1" placeholder="—" value={groupId} onChange={e => setGroupId(e.target.value)} />
                  </div>
                </div>
                <button
                  onClick={handleBatch}
                  disabled={batchPolling || !emails.trim() || noSolvers}
                  className="btn-primary w-full mt-2"
                >
                  {batchPolling ? (
                    <><Loader2 size={16} className="animate-spin" /> Выполняется...</>
                  ) : (
                    <><Play size={16} /> Запустить ({emails.split('\n').filter(l => l.trim()).length} шт.)</>
                  )}
                </button>
              </>
            )}
          </div>

          {/* Batch progress */}
          {batchStatus && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div className="text-xs text-[hsl(var(--muted-foreground))] uppercase tracking-wide mb-2">
                Прогресс (task: {batchStatus.task_id})
              </div>
              <div className="w-full bg-[hsl(var(--secondary))] rounded-full h-2 mb-3">
                <div
                  className="bg-green-500 h-2 rounded-full transition-all"
                  style={{ width: `${(batchStatus.completed / batchStatus.total) * 100}%` }}
                />
              </div>
              <div className="flex justify-between text-sm">
                <span>{batchStatus.completed} / {batchStatus.total}</span>
                <span className="text-green-400">{batchStatus.succeeded} ok</span>
                <span className="text-red-400">{batchStatus.failed} err</span>
              </div>
            </div>
          )}

          {/* Single result steps */}
          {singleResult && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div className={`text-sm font-semibold mb-2 ${singleResult.success ? 'text-green-400' : 'text-red-400'}`}>
                {singleResult.success ? 'Аккаунт создан' : 'Ошибка регистрации'}
              </div>
              {singleResult.success && (
                <div className="text-xs space-y-1 mb-3">
                  <div>Логин: <span className="font-mono text-[hsl(var(--foreground))]">{singleResult.login}</span></div>
                  <div>Пароль: <span className="font-mono text-[hsl(var(--foreground))]">{singleResult.password}</span></div>
                  {singleResult.steam_id && (
                    <div>SteamID: <span className="font-mono text-[hsl(var(--foreground))]">{singleResult.steam_id}</span></div>
                  )}
                </div>
              )}
              <div className="space-y-1">
                {singleResult.steps.map((s, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <StepIcon status={s.status} />
                    <span className="text-[hsl(var(--muted-foreground))]">{STEP_NAMES[s.step] || s.step}</span>
                    {s.detail && <span className="text-[hsl(var(--muted-foreground))] opacity-60 truncate max-w-[180px]">{s.detail}</span>}
                  </div>
                ))}
              </div>
              {singleResult.error && (
                <div className="mt-2 text-xs text-red-400">{singleResult.error}</div>
              )}
            </div>
          )}
        </div>

        {/* Right: Results log */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-[hsl(var(--muted-foreground))]">
              Лог регистрации ({results.length})
            </span>
            {results.length > 0 && (
              <button onClick={() => setResults([])} className="icon-btn" title="Очистить">
                <Trash2 size={14} />
              </button>
            )}
          </div>
          <div className="flex-1 overflow-auto rounded-lg border border-[hsl(var(--border))]">
            {results.length === 0 ? (
              <div className="flex items-center justify-center h-full text-[hsl(var(--muted-foreground))] text-sm">
                Результаты регистрации появятся здесь
              </div>
            ) : (
              <div className="divide-y divide-[hsl(var(--border))]">
                {results.map((r, idx) => (
                  <div key={idx} className="p-3">
                    <div
                      className="flex items-center gap-2 cursor-pointer"
                      onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                    >
                      {r.success ? (
                        <CheckCircle size={16} className="text-green-400 flex-shrink-0" />
                      ) : (
                        <XCircle size={16} className="text-red-400 flex-shrink-0" />
                      )}
                      <span className="font-mono text-sm">{r.login || r.email || '—'}</span>
                      <span className="text-xs text-[hsl(var(--muted-foreground))] ml-auto">
                        {r.email}
                      </span>
                      {expandedIdx === idx ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </div>
                    {expandedIdx === idx && (
                      <div className="mt-2 pl-6 space-y-1">
                        {r.success && (
                          <div className="text-xs space-y-0.5 mb-2">
                            <div>Логин: <span className="font-mono">{r.login}</span></div>
                            <div>Пароль: <span className="font-mono">{r.password}</span></div>
                            {r.steam_id && <div>SteamID: <span className="font-mono">{r.steam_id}</span></div>}
                            {r.account_id && <div>Account ID: <span className="font-mono">{r.account_id}</span></div>}
                          </div>
                        )}
                        {r.steps.map((s, si) => (
                          <div key={si} className="flex items-center gap-2 text-xs">
                            <StepIcon status={s.status} />
                            <span className="text-[hsl(var(--muted-foreground))]">{STEP_NAMES[s.step] || s.step}</span>
                            {s.detail && <span className="opacity-60 truncate max-w-[250px]">{s.detail}</span>}
                          </div>
                        ))}
                        {r.error && <div className="text-xs text-red-400 mt-1">{r.error}</div>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
