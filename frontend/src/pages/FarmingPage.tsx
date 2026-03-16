import { useState, useEffect, useCallback } from 'react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/Table'
import {
  Clock,
  Play,
  Plus,
  Square,
  RefreshCw,
  Gamepad2,
  Users,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Константы ────────────────────────────────────────────────

const PRESET_GAMES = [
  { appId: 730,     name: 'CS2' },
  { appId: 570,     name: 'Dota 2' },
  { appId: 440,     name: 'TF2' },
  { appId: 578080,  name: 'PUBG' },
  { appId: 1172470, name: 'Apex Legends' },
  { appId: 230410,  name: 'Warframe' },
  { appId: 1963000, name: 'The Finals' },
  { appId: 2767030, name: 'Marvel Rivals' },
  { appId: 238960,  name: 'Path of Exile' },
  { appId: 1085660, name: 'Destiny 2' },
]

// ─── Типы ─────────────────────────────────────────────────────

interface AsfBot {
  BotName: string
  IsConnectedAndLoggedOn: boolean
  CardsFarmer?: { CurrentGamesFarmed?: string }
}

interface FarmSession {
  bot_name: string
  app_ids: number[]
  hours_target: number
  started_at: number
  elapsed_hours: number
}

// ─── Компонент ────────────────────────────────────────────────

export function FarmingPage() {
  // Боты из ASF
  const [bots, setBots] = useState<AsfBot[]>([])
  const [botsLoading, setBotsLoading] = useState(true)
  const [asfRunning, setAsfRunning] = useState(false)

  // Выбор ботов
  const [selectedBots, setSelectedBots] = useState<Set<string>>(new Set())

  // Выбор игр
  const [selectedGames, setSelectedGames] = useState<Set<number>>(new Set([730]))
  const [customAppIds, setCustomAppIds] = useState('')

  // Рандомные игры
  const [randomGames, setRandomGames] = useState(false)
  const [randomCount, setRandomCount] = useState(3)

  // Часы
  const [hoursTarget, setHoursTarget] = useState<number>(0)

  // Фарм
  const [farmLoading, setFarmLoading] = useState(false)
  const [stopLoading, setStopLoading] = useState(false)
  const [addGamesLoading, setAddGamesLoading] = useState(false)

  // Активные сессии
  const [sessions, setSessions] = useState<FarmSession[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)

  // ─── Загрузка ─────────────────────────────────────────────

  const fetchBots = useCallback(async () => {
    try {
      const res = await api.get('/api/asf/status')
      setAsfRunning(res.data.running)
      setBots(res.data.bots ?? [])
    } catch {
      setAsfRunning(false)
      setBots([])
    } finally {
      setBotsLoading(false)
    }
  }, [])

  const fetchSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const res = await api.get('/api/asf/farm/sessions')
      setSessions(res.data.sessions ?? [])
    } catch {
      setSessions([])
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchBots()
    fetchSessions()
    const interval = setInterval(() => {
      fetchSessions()
    }, 15_000)
    return () => clearInterval(interval)
  }, [fetchBots, fetchSessions])

  // ─── Выбор ────────────────────────────────────────────────

  function toggleBot(name: string) {
    setSelectedBots((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function selectAllBots() {
    const online = bots.filter((b) => b.IsConnectedAndLoggedOn)
    if (selectedBots.size === online.length) {
      setSelectedBots(new Set())
    } else {
      setSelectedBots(new Set(online.map((b) => b.BotName)))
    }
  }

  function toggleGame(appId: number) {
    setSelectedGames((prev) => {
      const next = new Set(prev)
      if (next.has(appId)) next.delete(appId)
      else next.add(appId)
      return next
    })
  }

  function buildAppIds(): number[] {
    const ids = new Set<number>(selectedGames)
    customAppIds
      .split(',')
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !isNaN(n) && n > 0)
      .forEach((n) => ids.add(n))
    return Array.from(ids)
  }

  // ─── Действия ─────────────────────────────────────────────

  async function handleStartFarm() {
    const botNames = Array.from(selectedBots)
    const appIds = buildAppIds()

    if (botNames.length === 0) {
      alert('Выберите хотя бы одного бота')
      return
    }
    if (appIds.length === 0 && !randomGames) {
      alert('Выберите игры или включите рандомный режим')
      return
    }

    setFarmLoading(true)
    try {
      const res = await api.post('/api/asf/farm/start', {
        bot_names: botNames,
        app_ids: appIds,
        hours_target: hoursTarget,
        random_games: randomGames,
        random_count: randomCount,
      })
      const { started, errors } = res.data
      if (errors.length > 0) {
        alert(`Запущено: ${started.length}, ошибок: ${errors.length} (${errors.join(', ')})`)
      }
      await fetchSessions()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setFarmLoading(false)
    }
  }

  async function handleStopFarm() {
    const botNames = Array.from(selectedBots)
    if (botNames.length === 0) {
      alert('Выберите ботов для остановки')
      return
    }

    setStopLoading(true)
    try {
      await api.post('/api/asf/farm/stop', { bot_names: botNames })
      await fetchSessions()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setStopLoading(false)
    }
  }

  async function handleAddGames() {
    const botNames = Array.from(selectedBots)
    if (botNames.length === 0) {
      alert('Выберите ботов')
      return
    }
    setAddGamesLoading(true)
    try {
      const res = await api.post('/api/asf/farm/add-games', {
        bot_names: botNames,
        app_ids: buildAppIds(),
        random_games: randomGames,
        random_count: randomCount,
      })
      const results = res.data.results ?? []
      alert(`Добавление игр запущено для ${results.length} ботов. Проверьте консоль ASF для деталей.`)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setAddGamesLoading(false)
    }
  }

  async function handleStopSession(botName: string) {
    try {
      await api.post('/api/asf/farm/stop', { bot_names: [botName] })
      await fetchSessions()
    } catch {
      // ignore
    }
  }

  // ─── Рендер ───────────────────────────────────────────────

  const onlineBots = bots.filter((b) => b.IsConnectedAndLoggedOn)
  const appIds = buildAppIds()

  return (
    <div className="flex h-full flex-col gap-6 p-6">
      {/* ─── Заголовок ─── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Clock className="h-6 w-6 text-[hsl(var(--primary))]" />
          <h1 className="text-2xl font-bold">Фарм часов</h1>
        </div>
        <Button variant="ghost" size="icon" onClick={() => { fetchBots(); fetchSessions() }} title="Обновить">
          <RefreshCw className={cn('h-4 w-4', botsLoading && 'animate-spin')} />
        </Button>
      </div>

      {/* ─── Предупреждение если ASF не запущен ─── */}
      {!botsLoading && !asfRunning && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          ASF не запущен. Перейдите на вкладку «ASF Боты» и запустите ASF.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        {/* ─── Левая колонка: настройки фарма ─── */}
        <div className="flex flex-col gap-4">
          {/* Выбор ботов */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 font-semibold">
                <Users className="h-4 w-4" />
                Боты ({onlineBots.length} online)
              </h2>
              <button
                onClick={selectAllBots}
                className="text-xs text-[hsl(var(--primary))] hover:underline"
              >
                {selectedBots.size === onlineBots.length && onlineBots.length > 0
                  ? 'Снять всё'
                  : 'Выбрать всех online'}
              </button>
            </div>

            {botsLoading ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">Загрузка...</p>
            ) : bots.length === 0 ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">
                Нет добавленных ботов. Добавьте их в разделе «ASF Боты».
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">
                {bots.map((bot) => (
                  <label
                    key={bot.BotName}
                    className={cn(
                      'flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                      !bot.IsConnectedAndLoggedOn && 'cursor-not-allowed opacity-40',
                      selectedBots.has(bot.BotName)
                        ? 'bg-[hsl(var(--primary)/0.15)]'
                        : 'hover:bg-[hsl(var(--accent))]'
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={selectedBots.has(bot.BotName)}
                      onChange={() => bot.IsConnectedAndLoggedOn && toggleBot(bot.BotName)}
                      disabled={!bot.IsConnectedAndLoggedOn}
                      className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                    />
                    <span className="truncate font-mono">{bot.BotName}</span>
                    <span
                      className={cn(
                        'ml-auto h-2 w-2 shrink-0 rounded-full',
                        bot.IsConnectedAndLoggedOn ? 'bg-green-400' : 'bg-[hsl(var(--muted-foreground))]'
                      )}
                    />
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* Рандомные игры */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 font-semibold">
                <Gamepad2 className="h-4 w-4" />
                Рандомные игры
              </h2>
              <label className="flex cursor-pointer items-center gap-2">
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  {randomGames ? 'Вкл' : 'Выкл'}
                </span>
                <button
                  onClick={() => setRandomGames(!randomGames)}
                  className={cn(
                    'relative h-5 w-9 rounded-full transition-colors',
                    randomGames ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'
                  )}
                >
                  <span
                    className={cn(
                      'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform',
                      randomGames ? 'translate-x-4' : 'translate-x-0.5'
                    )}
                  />
                </button>
              </label>
            </div>
            {randomGames && (
              <div className="mt-3 flex items-center gap-3">
                <span className="text-sm text-[hsl(var(--muted-foreground))]">Игр на бота:</span>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    onClick={() => setRandomCount(n)}
                    className={cn(
                      'h-8 w-8 rounded-md text-sm font-medium transition-colors',
                      randomCount === n
                        ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                        : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
                    )}
                  >
                    {n}
                  </button>
                ))}
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  Каждый бот получит случайный набор из пула ~30 игр
                </span>
              </div>
            )}
          </div>

          {/* Выбор игр */}
          <div className={cn(
            "rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4",
            randomGames && "opacity-50"
          )}>
            <h2 className="mb-3 flex items-center gap-2 font-semibold">
              <Gamepad2 className="h-4 w-4" />
              {randomGames ? 'Дополнительные игры (будут добавлены к рандомным)' : 'Игры для фарма'}
            </h2>

            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {PRESET_GAMES.map((game) => (
                <label
                  key={game.appId}
                  className={cn(
                    'flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors',
                    selectedGames.has(game.appId)
                      ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.1)] text-[hsl(var(--primary))]'
                      : 'border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))] hover:bg-[hsl(var(--accent))]'
                  )}
                >
                  <input
                    type="checkbox"
                    checked={selectedGames.has(game.appId)}
                    onChange={() => toggleGame(game.appId)}
                    className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                  />
                  <span className="font-medium">{game.name}</span>
                  <span className="ml-auto text-xs opacity-60">{game.appId}</span>
                </label>
              ))}
            </div>

            <div>
              <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">
                Дополнительные AppID (через запятую)
              </label>
              <input
                value={customAppIds}
                onChange={(e) => setCustomAppIds(e.target.value)}
                placeholder="292030, 108600, ..."
                className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              />
            </div>
          </div>

          {/* Цель часов */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-3 flex items-center gap-2 font-semibold">
              <Clock className="h-4 w-4" />
              Цель (часов)
            </h2>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min={0}
                step={0.5}
                value={hoursTarget}
                onChange={(e) => setHoursTarget(parseFloat(e.target.value) || 0)}
                className="w-32 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              />
              <span className="text-sm text-[hsl(var(--muted-foreground))]">
                {hoursTarget === 0 ? 'бессрочно' : `фармить ${hoursTarget}ч`}
              </span>
            </div>
          </div>

          {/* Кнопки */}
          <div className="flex gap-3">
            <Button
              size="lg"
              className="flex-1"
              loading={farmLoading}
              disabled={!asfRunning || selectedBots.size === 0 || (appIds.length === 0 && !randomGames)}
              onClick={handleStartFarm}
            >
              <Play className="h-4 w-4" />
              Начать фарм ({selectedBots.size} ботов{randomGames ? `, ${randomCount} рандом` : `, ${appIds.length} игр`})
            </Button>
            <Button
              variant="outline"
              size="lg"
              loading={addGamesLoading}
              disabled={!asfRunning || selectedBots.size === 0 || (appIds.length === 0 && !randomGames)}
              onClick={handleAddGames}
              title="Добавить бесплатные игры в библиотеку без запуска фарма"
            >
              <Plus className="h-4 w-4" />
              Добавить игры
            </Button>
            <Button
              variant="outline"
              size="lg"
              loading={stopLoading}
              disabled={!asfRunning || selectedBots.size === 0}
              onClick={handleStopFarm}
            >
              <Square className="h-4 w-4" />
              Стоп
            </Button>
          </div>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Бесплатные игры автоматически добавляются в библиотеку при запуске фарма (addlicense)
          </p>
        </div>

        {/* ─── Правая колонка: активные сессии ─── */}
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">Активные сессии</h2>
              <button onClick={fetchSessions} className="text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                <RefreshCw className={cn('h-3 w-3', sessionsLoading && 'animate-spin')} />
              </button>
            </div>

            {sessions.length === 0 ? (
              <p className="text-center text-sm text-[hsl(var(--muted-foreground))]">
                Нет активных сессий
              </p>
            ) : (
              <div className="space-y-2">
                {sessions.map((s) => (
                  <div
                    key={s.bot_name}
                    className="rounded-md border border-[hsl(var(--border))] p-3"
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span className="font-mono text-sm font-medium">{s.bot_name}</span>
                      <button
                        onClick={() => handleStopSession(s.bot_name)}
                        className="text-[hsl(var(--destructive))] hover:opacity-70"
                        title="Остановить"
                      >
                        <Square className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className="text-xs text-[hsl(var(--muted-foreground))]">
                      <div>
                        Игры: {s.app_ids.map((id) => {
                          const preset = PRESET_GAMES.find((g) => g.appId === id)
                          return preset ? preset.name : id
                        }).join(', ')}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {s.elapsed_hours.toFixed(1)}ч
                        {s.hours_target > 0 && ` / ${s.hours_target}ч`}
                      </div>
                    </div>
                    {s.hours_target > 0 && (
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                        <div
                          className="h-full rounded-full bg-[hsl(var(--primary))] transition-all"
                          style={{
                            width: `${Math.min(100, (s.elapsed_hours / s.hours_target) * 100).toFixed(1)}%`,
                          }}
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Инфо */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 text-xs text-[hsl(var(--muted-foreground))]">
            <p className="mb-2 font-medium text-[hsl(var(--foreground))]">Как работает</p>
            <ul className="space-y-1">
              <li>• ASF фармит часы через команду <code className="rounded bg-[hsl(var(--muted))] px-1">play</code></li>
              <li>• Аккаунт отображается как «играющий» в Steam</li>
              <li>• CS2 / Dota 2 — для прогрева до 100 часов</li>
              <li>• Цель = 0 означает фарм без ограничений</li>
              <li>• Прогресс обновляется каждые 15 сек</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
