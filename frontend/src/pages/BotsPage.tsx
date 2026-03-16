import { useState, useEffect, useCallback, useRef } from 'react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/Table'
import {
  Bot,
  Play,
  Square,
  Plus,
  Trash2,
  RefreshCw,
  Wifi,
  WifiOff,
  Terminal,
  ChevronRight,
  Download,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Типы ────────────────────────────────────────────────────

interface AsfBot {
  BotName: string
  IsConnectedAndLoggedOn?: boolean
  IsRunning?: boolean
  IsFarmingPossible?: boolean
  CardsFarmer?: {
    CurrentGamesFarming?: { AppID: number; GameName: string }[]
    NowFarming?: boolean
    GamesToFarm?: unknown[]
  }
  WalletBalance?: number
  SteamID?: string
  status?: string  // "offline" | "initializing" из конфигов
}

interface ProxyItem {
  id: number
  host: string
  port: number
  protocol: string
  username: string | null
  is_alive: boolean
  country: string | null
}

interface AsfStatus {
  running: boolean
  ipc_available: boolean
  pid: number | null
  asf_info: Record<string, unknown> | null
  bots: AsfBot[]
  bot_configs: string[]
}

interface LocalAccount {
  id: string
  login: string
  password: string
  status: string
  maFile: boolean
  sharedSecret?: string
  maFileJson?: string
  steamId?: string
}

// ─── Хелперы ─────────────────────────────────────────────────

function botStatusBadge(bot: AsfBot) {
  if (!bot.IsConnectedAndLoggedOn) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-[hsl(var(--muted))] px-2 py-0.5 text-xs text-[hsl(var(--muted-foreground))]">
        <WifiOff className="h-3 w-3" /> Offline
      </span>
    )
  }
  if (bot.CardsFarmer?.NowFarming || (bot.CardsFarmer?.CurrentGamesFarming?.length ?? 0) > 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/20 px-2 py-0.5 text-xs text-blue-400">
        <Play className="h-3 w-3" /> Фарм
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-green-500/20 px-2 py-0.5 text-xs text-green-400">
      <Wifi className="h-3 w-3" /> Online
    </span>
  )
}

// ─── Компонент ───────────────────────────────────────────────

export function BotsPage() {
  const [asfStatus, setAsfStatus] = useState<AsfStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Модалка добавления ботов
  const [showAddModal, setShowAddModal] = useState(false)
  const [accounts, setAccounts] = useState<LocalAccount[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [addLoading, setAddLoading] = useState(false)
  const [proxies, setProxies] = useState<ProxyItem[]>([])
  const [selectedProxyId, setSelectedProxyId] = useState<number | null>(null)
  const [proxyMode, setProxyMode] = useState<'none' | 'single' | 'roundrobin'>('none')

  // Прогресс скачивания ASF
  const [downloadState, setDownloadState] = useState<{
    active: boolean; stage: string; percent: number; version: string; error: string
  } | null>(null)
  const downloadPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Модалка ASF Console
  const [showConsole, setShowConsole] = useState(false)
  const [consoleInput, setConsoleInput] = useState('')
  const [consoleLogs, setConsoleLogs] = useState<{ cmd: string; result: string }[]>([])
  const [consoleLoading, setConsoleLoading] = useState(false)

  // ─── Загрузка статуса ───────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get('/api/asf/status')
      setAsfStatus(res.data)
    } catch {
      // ASF модуль может быть не запущен — не показываем ошибку
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 10_000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  // ─── Прогресс скачивания ────────────────────────────────────

  function startDownloadPolling() {
    if (downloadPollRef.current) return
    downloadPollRef.current = setInterval(async () => {
      try {
        const res = await api.get('/api/asf/download/progress')
        setDownloadState(res.data)
        if (!res.data.active && res.data.stage === 'done') {
          stopDownloadPolling()
          // ASF скачан — _download_then_start() уже запускает его.
          // Polling статуса до running: true (ASF ждёт IPC ~30 сек)
          setDownloadState({ active: true, stage: 'starting', percent: 100, version: res.data.version ?? '', error: '' })
          const pollStart = setInterval(async () => {
            const sr = await api.get('/api/asf/status').catch(() => null)
            if (sr?.data?.running) {
              clearInterval(pollStart)
              setDownloadState(null)
              setAsfStatus(sr.data)
            }
          }, 2000)
          // Таймаут 60 сек
          setTimeout(() => { clearInterval(pollStart); setDownloadState(null); fetchStatus() }, 60000)
        }
        if (!res.data.active && res.data.stage === 'error') {
          stopDownloadPolling()
        }
      } catch {
        stopDownloadPolling()
      }
    }, 800)
  }

  function stopDownloadPolling() {
    if (downloadPollRef.current) {
      clearInterval(downloadPollRef.current)
      downloadPollRef.current = null
    }
  }

  useEffect(() => () => stopDownloadPolling(), [])

  // ─── Управление ASF процессом ───────────────────────────────

  async function handleStartAsf() {
    setActionLoading('start-asf')
    setDownloadState(null)
    try {
      // Увеличенный таймаут — ASF ждёт IPC до 30 сек
      const res = await api.post('/api/asf/start', {}, { timeout: 45000 })
      if (res.data.downloading) {
        startDownloadPolling()
      } else {
        await fetchStatus()
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка запуска ASF: ${msg}`)
    } finally {
      setActionLoading(null)
    }
  }

  async function handleStopAsf() {
    if (!confirm('Остановить ASF? Все боты выйдут из Steam.')) return
    setActionLoading('stop-asf')
    try {
      await api.post('/api/asf/stop')
      await fetchStatus()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка остановки ASF: ${msg}`)
    } finally {
      setActionLoading(null)
    }
  }

  // ─── Управление ботами ──────────────────────────────────────

  async function handleBotAction(name: string, action: 'start' | 'stop' | 'delete') {
    setActionLoading(`${action}-${name}`)
    try {
      if (action === 'delete') {
        if (!confirm(`Удалить бота ${name}? Конфиг будет удалён.`)) return
        await api.delete(`/api/asf/bots/${name}`)
      } else {
        await api.post(`/api/asf/bots/${name}/${action}`)
      }
      await fetchStatus()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setActionLoading(null)
    }
  }

  // ─── Добавление ботов ───────────────────────────────────────

  function openAddModal() {
    setShowAddModal(true)
    setSelectedIds(new Set())
    setSelectedProxyId(null)
    setProxyMode('none')
    // Загружаем аккаунты из localStorage
    try {
      const raw = localStorage.getItem('steam_accounts')
      setAccounts(raw ? JSON.parse(raw) : [])
    } catch {
      setAccounts([])
    }
    // Загружаем прокси из бэкенда
    api.get('/api/proxies/').then((res) => setProxies(res.data)).catch(() => setProxies([]))
  }

  function toggleAccount(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleAddBots() {
    if (selectedIds.size === 0) return
    setAddLoading(true)
    try {
      const selected = accounts.filter((a) => selectedIds.has(a.id))
      const aliveProxies = proxies.filter((p) => p.is_alive)
      const res = await api.post('/api/asf/bots/add-direct', {
        accounts: selected.map((a, idx) => ({
          login: a.login,
          password: a.password,
          shared_secret: a.sharedSecret || undefined,
          mafile_json: a.maFileJson || undefined,
          proxy_id: proxyMode === 'single' ? selectedProxyId
                  : proxyMode === 'roundrobin' && aliveProxies.length > 0
                    ? aliveProxies[idx % aliveProxies.length].id
                  : undefined,
        })),
      })
      const { added, errors } = res.data
      alert(`Добавлено: ${added}, ошибок: ${errors}`)
      setShowAddModal(false)
      await fetchStatus()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setAddLoading(false)
    }
  }

  // ─── ASF Console ────────────────────────────────────────────

  async function sendConsoleCommand() {
    if (!consoleInput.trim()) return
    const cmd = consoleInput.trim()
    setConsoleInput('')
    setConsoleLoading(true)
    try {
      const res = await api.post('/api/asf/command', { command: cmd })
      setConsoleLogs((prev) => [...prev, { cmd, result: res.data.result ?? '' }])
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка IPC'
      setConsoleLogs((prev) => [...prev, { cmd, result: `[ОШИБКА] ${msg}` }])
    } finally {
      setConsoleLoading(false)
    }
  }

  // ─── Рендер ─────────────────────────────────────────────────

  const bots: AsfBot[] = asfStatus?.bots ?? []

  return (
    <div className="flex h-full flex-col gap-6 p-6">
      {/* ─── Заголовок ─── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bot className="h-6 w-6 text-[hsl(var(--primary))]" />
          <h1 className="text-2xl font-bold">ASF Боты</h1>
          {/* Статус ASF процесса */}
          {!loading && (
            <span
              className={cn(
                'rounded-full px-2.5 py-0.5 text-xs font-medium',
                asfStatus?.running
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
              )}
            >
              {asfStatus?.running ? (asfStatus.ipc_available ? 'Running' : 'Starting...') : 'Stopped'}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={fetchStatus} title="Обновить">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </Button>

          {asfStatus?.running ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowConsole(true)}
              >
                <Terminal className="h-4 w-4" />
                Консоль
              </Button>
              <Button
                variant="destructive"
                size="sm"
                loading={actionLoading === 'stop-asf'}
                onClick={handleStopAsf}
              >
                <Square className="h-4 w-4" />
                Остановить ASF
              </Button>
            </>
          ) : (
            <Button
              variant="success"
              size="sm"
              loading={actionLoading === 'start-asf'}
              onClick={handleStartAsf}
            >
              <Play className="h-4 w-4" />
              Запустить ASF
            </Button>
          )}

          <Button size="sm" onClick={openAddModal}>
            <Plus className="h-4 w-4" />
            Добавить боты
          </Button>
        </div>
      </div>

      {/* ─── Прогресс скачивания ─── */}
      {downloadState && downloadState.stage !== 'done' && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <Download className="h-4 w-4 text-[hsl(var(--primary))]" />
              <span className="font-medium">
                {downloadState.stage === 'fetching_release' && 'Получение информации о релизе...'}
                {downloadState.stage === 'downloading' && `Скачивание ASF ${downloadState.version}...`}
                {downloadState.stage === 'extracting' && 'Распаковка...'}
                {downloadState.stage === 'starting' && 'Запуск ASF...'}
                {downloadState.stage === 'error' && `Ошибка: ${downloadState.error}`}
              </span>
            </div>
            {downloadState.stage === 'downloading' && (
              <span className="text-[hsl(var(--muted-foreground))]">{downloadState.percent}%</span>
            )}
          </div>
          {downloadState.stage === 'downloading' && (
            <div className="h-2 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
              <div
                className="h-full rounded-full bg-[hsl(var(--primary))] transition-all duration-300"
                style={{ width: `${downloadState.percent}%` }}
              />
            </div>
          )}
          {downloadState.stage === 'error' && (
            <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{downloadState.error}</p>
          )}
        </div>
      )}

      {/* ─── Подсказка если ASF не настроен ─── */}
      {!loading && !asfStatus?.running && (asfStatus?.bot_configs.length ?? 0) === 0 && !downloadState?.active && (
        <div className="rounded-lg border border-dashed border-[hsl(var(--border-strong))] p-8 text-center">
          <Bot className="mx-auto mb-3 h-10 w-10 text-[hsl(var(--muted-foreground))]" />
          <p className="mb-1 font-medium">ASF не установлен</p>
          <p className="mb-4 text-sm text-[hsl(var(--muted-foreground))]">
            Нажмите «Запустить ASF» — бэкенд автоматически скачает и установит ASF с GitHub
          </p>
          <Button onClick={handleStartAsf} loading={actionLoading === 'start-asf'}>
            <Download className="h-4 w-4" />
            Скачать и запустить ASF
          </Button>
        </div>
      )}

      {/* ─── Таблица ботов ─── */}
      {bots.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Логин</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead>Игры</TableHead>
                <TableHead>Steam ID</TableHead>
                <TableHead className="text-right">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bots.map((bot) => (
                <TableRow key={bot.BotName}>
                  <TableCell className="font-mono font-medium">{bot.BotName}</TableCell>
                  <TableCell>{botStatusBadge(bot)}</TableCell>
                  <TableCell className="text-[hsl(var(--muted-foreground))]">
                    {bot.CardsFarmer?.CurrentGamesFarming?.length
                      ? bot.CardsFarmer.CurrentGamesFarming.map((g) => g.GameName || g.AppID).join(', ')
                      : '—'}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[hsl(var(--muted-foreground))]">
                    {bot.SteamID ?? '—'}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      {bot.IsConnectedAndLoggedOn ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Стоп"
                          loading={actionLoading === `stop-${bot.BotName}`}
                          onClick={() => handleBotAction(bot.BotName, 'stop')}
                        >
                          <Square className="h-4 w-4" />
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="icon"
                          title="Старт"
                          loading={actionLoading === `start-${bot.BotName}`}
                          onClick={() => handleBotAction(bot.BotName, 'start')}
                        >
                          <Play className="h-4 w-4" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        title="Удалить"
                        loading={actionLoading === `delete-${bot.BotName}`}
                        onClick={() => handleBotAction(bot.BotName, 'delete')}
                      >
                        <Trash2 className="h-4 w-4 text-[hsl(var(--destructive))]" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ─── Модалка добавления ботов ─── */}
      <Modal open={showAddModal} onClose={() => setShowAddModal(false)} className="max-w-lg">
        <ModalHeader onClose={() => setShowAddModal(false)}>
          Добавить аккаунты как боты
        </ModalHeader>
        <ModalBody>
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs">Выберите аккаунты. Для каждого будет сгенерирован конфиг бота.</p>
            {accounts.length > 0 && (
              <button
                onClick={() => {
                  if (selectedIds.size === accounts.length) setSelectedIds(new Set())
                  else setSelectedIds(new Set(accounts.map((a) => a.id)))
                }}
                className="text-xs text-[hsl(var(--primary))] hover:underline whitespace-nowrap ml-2"
              >
                {selectedIds.size === accounts.length ? 'Снять всё' : 'Выбрать всех'}
              </button>
            )}
          </div>
          {accounts.length === 0 ? (
            <p className="text-center text-[hsl(var(--muted-foreground))]">
              Нет аккаунтов в базе данных
            </p>
          ) : (
            <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
              {accounts.map((acc) => (
                <label
                  key={acc.id}
                  className={cn(
                    'flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 transition-colors',
                    selectedIds.has(acc.id)
                      ? 'bg-[hsl(var(--primary)/0.15)]'
                      : 'hover:bg-[hsl(var(--accent))]'
                  )}
                >
                  <input
                    type="checkbox"
                    checked={selectedIds.has(acc.id)}
                    onChange={() => toggleAccount(acc.id)}
                    className="h-4 w-4 rounded accent-[hsl(var(--primary))]"
                  />
                  <span className="flex-1 font-mono text-sm">{acc.login}</span>
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">
                    {acc.maFile ? '🔑 maFile' : 'без 2FA'}
                  </span>
                  {acc.status === 'active' && (
                    <span className="rounded-full bg-green-500/20 px-1.5 py-0.5 text-xs text-green-400">
                      active
                    </span>
                  )}
                </label>
              ))}
            </div>
          )}
          {/* Прокси */}
          <div className="mt-4 border-t border-[hsl(var(--border))] pt-3">
            <p className="mb-2 text-xs font-medium">Прокси для ботов</p>
            <div className="flex gap-2 mb-2">
              {(['none', 'single', 'roundrobin'] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setProxyMode(mode)}
                  className={cn(
                    'rounded-md px-3 py-1 text-xs transition-colors',
                    proxyMode === mode
                      ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                      : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
                  )}
                >
                  {mode === 'none' ? 'Без прокси' : mode === 'single' ? 'Один на всех' : 'Round-robin'}
                </button>
              ))}
            </div>
            {proxyMode === 'single' && (
              <select
                value={selectedProxyId ?? ''}
                onChange={(e) => setSelectedProxyId(e.target.value ? Number(e.target.value) : null)}
                className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm"
              >
                <option value="">Выберите прокси</option>
                {proxies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.host}:{p.port} {p.country ? `(${p.country})` : ''} {p.is_alive ? '' : ' [offline]'}
                  </option>
                ))}
              </select>
            )}
            {proxyMode === 'roundrobin' && (
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Каждому боту — свой прокси по очереди ({proxies.filter((p) => p.is_alive).length} активных)
              </p>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          <span className="mr-auto text-xs text-[hsl(var(--muted-foreground))]">
            Выбрано: {selectedIds.size}
          </span>
          <Button variant="outline" onClick={() => setShowAddModal(false)}>
            Отмена
          </Button>
          <Button
            onClick={handleAddBots}
            disabled={selectedIds.size === 0}
            loading={addLoading}
          >
            <Plus className="h-4 w-4" />
            Добавить ({selectedIds.size})
          </Button>
        </ModalFooter>
      </Modal>

      {/* ─── ASF Console ─── */}
      <Modal open={showConsole} onClose={() => setShowConsole(false)} className="max-w-2xl">
        <ModalHeader onClose={() => setShowConsole(false)}>
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            ASF Console
          </div>
        </ModalHeader>
        <ModalBody>
          {/* Лог */}
          <div className="mb-3 h-56 overflow-y-auto rounded-md bg-black/40 p-3 font-mono text-xs">
            {consoleLogs.length === 0 ? (
              <span className="text-[hsl(var(--muted-foreground))]">
                Введите команду ASF... Например: status ASF, play BotName 730
              </span>
            ) : (
              consoleLogs.map((entry, i) => (
                <div key={i} className="mb-2">
                  <div className="text-[hsl(var(--primary))]">&gt; {entry.cmd}</div>
                  <div className="whitespace-pre-wrap text-[hsl(var(--foreground))]">
                    {entry.result}
                  </div>
                </div>
              ))
            )}
          </div>
          {/* Ввод */}
          <div className="flex gap-2">
            <input
              value={consoleInput}
              onChange={(e) => setConsoleInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendConsoleCommand()}
              placeholder="status ASF"
              className="flex-1 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 font-mono text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
            />
            <Button onClick={sendConsoleCommand} loading={consoleLoading} size="sm">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </ModalBody>
      </Modal>
    </div>
  )
}
