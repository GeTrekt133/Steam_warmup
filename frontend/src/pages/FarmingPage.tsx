import { useState, useEffect, useCallback } from 'react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import {
  Clock,
  Play,
  Plus,
  Square,
  RefreshCw,
  Gamepad2,
  Users,
  Brain,
  Calendar,
  Coffee,
  Shuffle,
  Zap,
  UserCircle,
  Pencil,
  Trash2,
  X,
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

// Расширенный список для профилей (включая платные популярные)
const ALL_GAMES = [
  ...PRESET_GAMES,
  { appId: 304930,  name: 'Unturned' },
  { appId: 444090,  name: 'Paladins' },
  { appId: 386360,  name: 'SMITE' },
  { appId: 236390,  name: 'War Thunder' },
  { appId: 1599340, name: 'Lost Ark' },
  { appId: 1366540, name: 'Enlisted' },
  { appId: 1097150, name: 'Fall Guys' },
  { appId: 2399830, name: 'Overwatch 2' },
  { appId: 3221870, name: 'Delta Force' },
  { appId: 945360,  name: 'Among Us' },
]

const GAME_NAME_MAP: Record<number, string> = {}
for (const g of ALL_GAMES) GAME_NAME_MAP[g.appId] = g.name

// ─── Профили игроков ─────────────────────────────────────────

interface GameWeight {
  appId: number
  weight: number  // 1-100, не обязательно в сумме 100 (нормализуем при отправке)
}

interface GameProfile {
  id: string
  name: string
  games: GameWeight[]
}

const DEFAULT_PROFILES: GameProfile[] = [
  {
    id: 'preset_cs2',
    name: 'CS2 Игрок',
    games: [
      { appId: 730, weight: 60 },
      { appId: 570, weight: 15 },
      { appId: 440, weight: 10 },
      { appId: 578080, weight: 10 },
      { appId: 1172470, weight: 5 },
    ],
  },
  {
    id: 'preset_dota',
    name: 'Дотер',
    games: [
      { appId: 570, weight: 55 },
      { appId: 730, weight: 20 },
      { appId: 2767030, weight: 15 },
      { appId: 440, weight: 10 },
    ],
  },
  {
    id: 'preset_warthunder',
    name: 'War Thunder',
    games: [
      { appId: 236390, weight: 50 },
      { appId: 730, weight: 20 },
      { appId: 1366540, weight: 15 },
      { appId: 440, weight: 10 },
      { appId: 578080, weight: 5 },
    ],
  },
  {
    id: 'preset_universal',
    name: 'Универсальный',
    games: [
      { appId: 730, weight: 20 },
      { appId: 570, weight: 20 },
      { appId: 440, weight: 15 },
      { appId: 230410, weight: 15 },
      { appId: 1085660, weight: 15 },
      { appId: 1963000, weight: 15 },
    ],
  },
]

function loadProfiles(): GameProfile[] {
  try {
    const raw = localStorage.getItem('farming_profiles')
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return [...DEFAULT_PROFILES]
}

function saveProfiles(profiles: GameProfile[]) {
  localStorage.setItem('farming_profiles', JSON.stringify(profiles))
}

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

interface SmartSession {
  session_id: string
  status: string
  config: Record<string, unknown>
  elapsed_hours: number
  total_hours_farmed: number
  breaks_taken: number
  rotations_done: number
  current_apps: Record<string, number[]>
  error: string | null
}

type FarmMode = 'manual' | 'smart'

// ─── Компонент ────────────────────────────────────────────────

export function FarmingPage() {
  // Режим
  const [mode, setMode] = useState<FarmMode>('manual')

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

  // Активные сессии (manual)
  const [sessions, setSessions] = useState<FarmSession[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)

  // Smart Farming
  const [smartSessions, setSmartSessions] = useState<SmartSession[]>([])
  const [smartLoading, setSmartLoading] = useState(false)
  const [smartStopLoading, setSmartStopLoading] = useState<string | null>(null)

  // Smart Farming настройки
  const [activeStartHour, setActiveStartHour] = useState(8)
  const [activeEndHour, setActiveEndHour] = useState(23)
  const [breakIntervalMin, setBreakIntervalMin] = useState(2)
  const [breakIntervalMax, setBreakIntervalMax] = useState(4)
  const [breakDurationMin, setBreakDurationMin] = useState(15)
  const [breakDurationMax, setBreakDurationMax] = useState(45)
  const [gameRotationHours, setGameRotationHours] = useState(3)
  const [gamesPerRotation, setGamesPerRotation] = useState(1)
  const [startJitter, setStartJitter] = useState(30)
  const [simulateSwitching, setSimulateSwitching] = useState(true)

  // Профили игроков
  const [profiles, setProfiles] = useState<GameProfile[]>(() => loadProfiles())
  const [selectedProfileIds, setSelectedProfileIds] = useState<Set<string>>(new Set())
  const [showProfileModal, setShowProfileModal] = useState(false)
  const [editingProfile, setEditingProfile] = useState<GameProfile | null>(null)

  // Состояние модалки редактирования профиля
  const [profileName, setProfileName] = useState('')
  const [profileGames, setProfileGames] = useState<GameWeight[]>([])
  const [addGameId, setAddGameId] = useState<string>('')

  function openCreateProfile() {
    setEditingProfile(null)
    setProfileName('')
    setProfileGames([{ appId: 730, weight: 50 }])
    setAddGameId('')
    setShowProfileModal(true)
  }

  function openEditProfile(profile: GameProfile) {
    setEditingProfile(profile)
    setProfileName(profile.name)
    setProfileGames([...profile.games])
    setAddGameId('')
    setShowProfileModal(true)
  }

  function handleSaveProfile() {
    if (!profileName.trim()) return
    const filtered = profileGames.filter(g => g.weight > 0)
    if (filtered.length === 0) return

    const updated = [...profiles]
    if (editingProfile) {
      const idx = updated.findIndex(p => p.id === editingProfile.id)
      if (idx >= 0) {
        updated[idx] = { ...updated[idx], name: profileName.trim(), games: filtered }
      }
    } else {
      updated.push({
        id: `profile_${Date.now()}`,
        name: profileName.trim(),
        games: filtered,
      })
    }
    setProfiles(updated)
    saveProfiles(updated)
    setShowProfileModal(false)
  }

  function handleDeleteProfile(id: string) {
    const updated = profiles.filter(p => p.id !== id)
    setProfiles(updated)
    saveProfiles(updated)
    setSelectedProfileIds(prev => { const next = new Set(prev); next.delete(id); return next })
  }

  function handleAddGameToProfile() {
    const appId = parseInt(addGameId)
    if (!appId || profileGames.some(g => g.appId === appId)) return
    setProfileGames([...profileGames, { appId, weight: 10 }])
    setAddGameId('')
  }

  function handleRemoveGameFromProfile(appId: number) {
    setProfileGames(profileGames.filter(g => g.appId !== appId))
  }

  function handleGameWeightChange(appId: number, weight: number) {
    setProfileGames(profileGames.map(g => g.appId === appId ? { ...g, weight: Math.max(1, Math.min(100, weight)) } : g))
  }

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

  const fetchSmartSessions = useCallback(async () => {
    try {
      const res = await api.get('/api/asf/farm/smart-sessions')
      setSmartSessions(res.data.sessions ?? [])
    } catch {
      setSmartSessions([])
    }
  }, [])

  useEffect(() => {
    fetchBots()
    fetchSessions()
    fetchSmartSessions()
    const interval = setInterval(() => {
      fetchSessions()
      fetchSmartSessions()
    }, 15_000)
    return () => clearInterval(interval)
  }, [fetchBots, fetchSessions, fetchSmartSessions])

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

  // ─── Действия (manual) ─────────────────────────────────────

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

  // ─── Действия (smart) ──────────────────────────────────────

  async function handleStartSmart() {
    const botNames = Array.from(selectedBots)
    if (botNames.length === 0) {
      alert('Выберите хотя бы одного бота')
      return
    }

    setSmartLoading(true)
    try {
      // Собираем профили для рандомного распределения по ботам
      const selectedProfiles = profiles.filter(p => selectedProfileIds.has(p.id))
      const profileWeightsList = selectedProfiles.map(p => {
        const w: Record<string, number> = {}
        for (const g of p.games) w[String(g.appId)] = g.weight
        return w
      })

      await api.post('/api/asf/farm/smart-start', {
        bot_names: botNames,
        app_ids: buildAppIds(),
        game_weights_pool: profileWeightsList.length > 0 ? profileWeightsList : undefined,
        active_start_hour: activeStartHour,
        active_end_hour: activeEndHour,
        start_jitter_minutes: startJitter,
        stop_jitter_minutes: startJitter,
        break_interval_hours_min: breakIntervalMin,
        break_interval_hours_max: breakIntervalMax,
        break_duration_minutes_min: breakDurationMin,
        break_duration_minutes_max: breakDurationMax,
        game_rotation_hours: gameRotationHours,
        games_per_rotation: gamesPerRotation,
        use_random_games: selectedProfiles.length === 0 && (randomGames || buildAppIds().length === 0),
        simulate_game_switching: simulateSwitching,
      })
      await fetchSmartSessions()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setSmartLoading(false)
    }
  }

  async function handleStopSmart(sessionId: string) {
    setSmartStopLoading(sessionId)
    try {
      await api.post('/api/asf/farm/smart-stop', { session_id: sessionId })
      await fetchSmartSessions()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      alert(`Ошибка: ${msg}`)
    } finally {
      setSmartStopLoading(null)
    }
  }

  // ─── Общие части UI ────────────────────────────────────────

  const onlineBots = bots.filter((b) => b.IsConnectedAndLoggedOn)
  const appIds = buildAppIds()

  const statusColors: Record<string, string> = {
    active: 'text-green-400',
    paused: 'text-yellow-400',
    break: 'text-orange-400',
    stopped: 'text-[hsl(var(--muted-foreground))]',
    error: 'text-red-400',
    pending: 'text-blue-400',
  }

  const statusLabels: Record<string, string> = {
    active: 'Активен',
    paused: 'Пауза (вне окна)',
    break: 'Перерыв',
    stopped: 'Остановлен',
    error: 'Ошибка',
    pending: 'Запуск...',
  }

  // ─── Рендер ─────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col gap-6 p-6">
      {/* ─── Заголовок ─── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Clock className="h-6 w-6 text-[hsl(var(--primary))]" />
          <h1 className="text-2xl font-bold">Фарм часов</h1>
        </div>
        <Button variant="ghost" size="icon" onClick={() => { fetchBots(); fetchSessions(); fetchSmartSessions() }} title="Обновить">
          <RefreshCw className={cn('h-4 w-4', botsLoading && 'animate-spin')} />
        </Button>
      </div>

      {/* ─── Переключатель режимов ─── */}
      <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1">
        <button
          onClick={() => setMode('manual')}
          className={cn(
            'flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors',
            mode === 'manual'
              ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          )}
        >
          <Zap className="h-4 w-4" />
          Обычный фарм
        </button>
        <button
          onClick={() => setMode('smart')}
          className={cn(
            'flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors',
            mode === 'smart'
              ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          )}
        >
          <Brain className="h-4 w-4" />
          Умный фарм
        </button>
      </div>

      {/* ─── Предупреждение если ASF не запущен ─── */}
      {!botsLoading && !asfRunning && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          ASF не запущен. Перейдите на вкладку «ASF Боты» и запустите ASF.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        {/* ─── Левая колонка ─── */}
        <div className="flex flex-col gap-4">
          {/* Выбор ботов (общий для обоих режимов) */}
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

          {/* ─── Manual Mode ─── */}
          {mode === 'manual' && (
            <>
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
            </>
          )}

          {/* ─── Smart Mode ─── */}
          {mode === 'smart' && (
            <>
              {/* Расписание */}
              <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                <h2 className="mb-3 flex items-center gap-2 font-semibold">
                  <Calendar className="h-4 w-4" />
                  Окно активности
                </h2>
                <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
                  Фарм работает только в это время. Вне окна — пауза.
                </p>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">С</span>
                    <input
                      type="number" min={0} max={23}
                      value={activeStartHour}
                      onChange={(e) => setActiveStartHour(Math.max(0, Math.min(23, parseInt(e.target.value) || 0)))}
                      className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                    />
                    <span className="text-sm text-[hsl(var(--muted-foreground))]">:00</span>
                  </div>
                  <span className="text-[hsl(var(--muted-foreground))]">—</span>
                  <div className="flex items-center gap-2">
                    <span className="text-sm">До</span>
                    <input
                      type="number" min={0} max={24}
                      value={activeEndHour}
                      onChange={(e) => setActiveEndHour(Math.max(0, Math.min(24, parseInt(e.target.value) || 0)))}
                      className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                    />
                    <span className="text-sm text-[hsl(var(--muted-foreground))]">:00</span>
                  </div>
                  <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">
                    ({activeEndHour - activeStartHour > 0 ? activeEndHour - activeStartHour : 24 + activeEndHour - activeStartHour}ч в день)
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <span className="text-sm text-[hsl(var(--muted-foreground))]">Jitter старта:</span>
                  <input
                    type="number" min={0} max={60}
                    value={startJitter}
                    onChange={(e) => setStartJitter(Math.max(0, parseInt(e.target.value) || 0))}
                    className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                  />
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">мин (±{startJitter} мин от заданного времени)</span>
                </div>
              </div>

              {/* Перерывы */}
              <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                <h2 className="mb-3 flex items-center gap-2 font-semibold">
                  <Coffee className="h-4 w-4" />
                  Перерывы
                </h2>
                <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
                  Случайные паузы для имитации живого пользователя.
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Интервал (часы)</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number" min={0.5} max={12} step={0.5}
                        value={breakIntervalMin}
                        onChange={(e) => setBreakIntervalMin(parseFloat(e.target.value) || 1)}
                        className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                      />
                      <span className="text-sm text-[hsl(var(--muted-foreground))]">—</span>
                      <input
                        type="number" min={0.5} max={12} step={0.5}
                        value={breakIntervalMax}
                        onChange={(e) => setBreakIntervalMax(parseFloat(e.target.value) || 2)}
                        className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                      />
                      <span className="text-xs text-[hsl(var(--muted-foreground))]">ч</span>
                    </div>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Длительность (мин)</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number" min={1} max={120}
                        value={breakDurationMin}
                        onChange={(e) => setBreakDurationMin(parseInt(e.target.value) || 5)}
                        className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                      />
                      <span className="text-sm text-[hsl(var(--muted-foreground))]">—</span>
                      <input
                        type="number" min={1} max={120}
                        value={breakDurationMax}
                        onChange={(e) => setBreakDurationMax(parseInt(e.target.value) || 15)}
                        className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                      />
                      <span className="text-xs text-[hsl(var(--muted-foreground))]">мин</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Профиль игрока */}
              <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="flex items-center gap-2 font-semibold">
                    <UserCircle className="h-4 w-4" />
                    Профиль игрока
                  </h2>
                  <button
                    onClick={openCreateProfile}
                    className="flex items-center gap-1 rounded-md bg-[hsl(var(--muted))] px-2 py-1 text-xs hover:bg-[hsl(var(--accent))]"
                  >
                    <Plus className="h-3 w-3" />
                    Создать
                  </button>
                </div>
                <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
                  Выбери один или несколько профилей. Каждому боту рандомно назначается один из выбранных.
                  Если ничего не выбрано — равный рандом из пула F2P игр.
                </p>

                {/* Список профилей */}
                <div className="space-y-1.5">
                  {profiles.map((profile) => {
                    const totalWeight = profile.games.reduce((s, g) => s + g.weight, 0)
                    const isSelected = selectedProfileIds.has(profile.id)
                    return (
                      <label
                        key={profile.id}
                        className={cn(
                          'flex cursor-pointer items-center gap-3 rounded-md border p-2.5 transition-colors',
                          isSelected
                            ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.1)]'
                            : 'border-[hsl(var(--border))] hover:bg-[hsl(var(--accent)/0.5)]'
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {
                            setSelectedProfileIds(prev => {
                              const next = new Set(prev)
                              if (next.has(profile.id)) next.delete(profile.id)
                              else next.add(profile.id)
                              return next
                            })
                          }}
                          className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{profile.name}</span>
                          </div>
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            {profile.games.slice(0, 5).map((g) => (
                              <span
                                key={g.appId}
                                className="inline-flex items-center gap-1 rounded bg-[hsl(var(--muted))] px-1.5 py-0.5 text-[10px]"
                              >
                                {GAME_NAME_MAP[g.appId] || g.appId}
                                <span className="text-[hsl(var(--muted-foreground))]">
                                  {Math.round((g.weight / totalWeight) * 100)}%
                                </span>
                              </span>
                            ))}
                            {profile.games.length > 5 && (
                              <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                                +{profile.games.length - 5}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={(e) => { e.preventDefault(); openEditProfile(profile) }}
                            className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                            title="Редактировать"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={(e) => { e.preventDefault(); handleDeleteProfile(profile.id) }}
                            className="rounded p-1 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--destructive))]"
                            title="Удалить"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </label>
                    )
                  })}

                  {selectedProfileIds.size === 0 && (
                    <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                      Ни один профиль не выбран — будет использован рандом из пула F2P игр
                    </p>
                  )}
                </div>
              </div>

              {/* Ротация игр */}
              <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                <h2 className="mb-3 flex items-center gap-2 font-semibold">
                  <Shuffle className="h-4 w-4" />
                  Ротация игр
                </h2>
                <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
                  Меняет набор игр каждые N часов. Имитирует переключение между играми.
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Менять каждые</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number" min={0.5} max={24} step={0.5}
                        value={gameRotationHours}
                        onChange={(e) => setGameRotationHours(parseFloat(e.target.value) || 1)}
                        className="w-16 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                      />
                      <span className="text-xs text-[hsl(var(--muted-foreground))]">часов</span>
                    </div>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Игр за ротацию</label>
                    <div className="flex items-center gap-2">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <button
                          key={n}
                          onClick={() => setGamesPerRotation(n)}
                          className={cn(
                            'h-8 w-8 rounded-md text-sm font-medium transition-colors',
                            gamesPerRotation === n
                              ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                              : 'bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))]'
                          )}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={simulateSwitching}
                      onChange={(e) => setSimulateSwitching(e.target.checked)}
                      className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                    />
                    <span className="text-sm">Имитировать переключение</span>
                  </label>
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">
                    (сначала выйти из игры, потом зайти в другую)
                  </span>
                </div>
              </div>

              {/* Кнопка запуска */}
              <Button
                size="lg"
                className="w-full"
                loading={smartLoading}
                disabled={selectedBots.size === 0}
                onClick={handleStartSmart}
              >
                <Brain className="h-4 w-4" />
                Запустить умный фарм ({selectedBots.size} ботов, {activeStartHour}:00–{activeEndHour}:00)
              </Button>
            </>
          )}
        </div>

        {/* ─── Правая колонка: сессии ─── */}
        <div className="flex flex-col gap-4">
          {/* Manual Sessions */}
          {mode === 'manual' && (
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
          )}

          {/* Smart Sessions */}
          {mode === 'smart' && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="font-semibold">Smart Farming сессии</h2>
                <button onClick={fetchSmartSessions} className="text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                  <RefreshCw className="h-3 w-3" />
                </button>
              </div>

              {smartSessions.length === 0 ? (
                <p className="text-center text-sm text-[hsl(var(--muted-foreground))]">
                  Нет активных сессий
                </p>
              ) : (
                <div className="space-y-3">
                  {smartSessions.map((s) => (
                    <div
                      key={s.session_id}
                      className="rounded-md border border-[hsl(var(--border))] p-3"
                    >
                      <div className="mb-2 flex items-center justify-between">
                        <span className={cn('text-sm font-medium', statusColors[s.status] ?? 'text-[hsl(var(--foreground))]')}>
                          {statusLabels[s.status] ?? s.status}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={smartStopLoading === s.session_id}
                          onClick={() => handleStopSmart(s.session_id)}
                          className="h-7 px-2 text-xs text-[hsl(var(--destructive))]"
                        >
                          <Square className="h-3 w-3" />
                          Стоп
                        </Button>
                      </div>

                      {/* Текущие игры */}
                      {Object.entries(s.current_apps).length > 0 && (
                        <div className="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
                          {Object.entries(s.current_apps).map(([bot, apps]) => (
                            <div key={bot} className="flex gap-1">
                              <span className="font-mono">{bot}:</span>
                              <span>
                                {(apps as number[]).map((id) => {
                                  const preset = PRESET_GAMES.find((g) => g.appId === id)
                                  return preset ? preset.name : id
                                }).join(', ')}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Статистика */}
                      <div className="grid grid-cols-3 gap-2 text-center text-xs">
                        <div className="rounded-md bg-[hsl(var(--muted))] px-2 py-1.5">
                          <div className="font-medium">{s.total_hours_farmed.toFixed(1)}ч</div>
                          <div className="text-[hsl(var(--muted-foreground))]">Нафармлено</div>
                        </div>
                        <div className="rounded-md bg-[hsl(var(--muted))] px-2 py-1.5">
                          <div className="font-medium">{s.breaks_taken}</div>
                          <div className="text-[hsl(var(--muted-foreground))]">Перерывов</div>
                        </div>
                        <div className="rounded-md bg-[hsl(var(--muted))] px-2 py-1.5">
                          <div className="font-medium">{s.rotations_done}</div>
                          <div className="text-[hsl(var(--muted-foreground))]">Ротаций</div>
                        </div>
                      </div>

                      {s.error && (
                        <div className="mt-2 rounded bg-red-500/10 px-2 py-1 text-xs text-red-400">
                          {s.error}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Инфо */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 text-xs text-[hsl(var(--muted-foreground))]">
            <p className="mb-2 font-medium text-[hsl(var(--foreground))]">
              {mode === 'manual' ? 'Как работает' : 'Умный фарм'}
            </p>
            {mode === 'manual' ? (
              <ul className="space-y-1">
                <li>• ASF фармит часы через команду <code className="rounded bg-[hsl(var(--muted))] px-1">play</code></li>
                <li>• Аккаунт отображается как «играющий» в Steam</li>
                <li>• CS2 / Dota 2 — для прогрева до 100 часов</li>
                <li>• Цель = 0 означает фарм без ограничений</li>
                <li>• Прогресс обновляется каждые 15 сек</li>
              </ul>
            ) : (
              <ul className="space-y-1">
                <li>• Фарм только в заданные часы (окно активности)</li>
                <li>• Случайные перерывы — имитация живого пользователя</li>
                <li>• Ротация игр — меняет набор каждые N часов</li>
                <li>• Jitter старта — рандомное отклонение ±N мин</li>
                <li>• Имитация переключения — выход → пауза → вход</li>
                <li>• Всё для снижения риска бана Steam</li>
              </ul>
            )}
          </div>
        </div>
      </div>

      {/* ─── Модалка профиля игрока ─── */}
      {showProfileModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-lg rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                {editingProfile ? 'Редактировать профиль' : 'Новый профиль'}
              </h2>
              <button onClick={() => setShowProfileModal(false)} className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Название */}
            <div className="mb-4">
              <label className="mb-1 block text-sm text-[hsl(var(--muted-foreground))]">Название профиля</label>
              <input
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                placeholder="CS2 Игрок"
                className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              />
            </div>

            {/* Игры и веса */}
            <div className="mb-4">
              <label className="mb-2 block text-sm text-[hsl(var(--muted-foreground))]">
                Игры и веса (чем больше вес — тем чаще игра в ротации)
              </label>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {profileGames.map((g) => {
                  const totalWeight = profileGames.reduce((s, x) => s + x.weight, 0)
                  const pct = totalWeight > 0 ? Math.round((g.weight / totalWeight) * 100) : 0
                  return (
                    <div key={g.appId} className="flex items-center gap-2">
                      <span className="w-28 truncate text-sm font-medium">
                        {GAME_NAME_MAP[g.appId] || `App ${g.appId}`}
                      </span>
                      <input
                        type="range"
                        min={1}
                        max={100}
                        value={g.weight}
                        onChange={(e) => handleGameWeightChange(g.appId, parseInt(e.target.value))}
                        className="h-1.5 flex-1 accent-[hsl(var(--primary))]"
                      />
                      <span className="w-10 text-right text-xs text-[hsl(var(--muted-foreground))]">
                        {pct}%
                      </span>
                      <button
                        onClick={() => handleRemoveGameFromProfile(g.appId)}
                        className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--destructive))]"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Добавить игру */}
            <div className="mb-5 flex gap-2">
              <select
                value={addGameId}
                onChange={(e) => setAddGameId(e.target.value)}
                className="flex-1 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-sm outline-none"
              >
                <option value="">Добавить игру...</option>
                {ALL_GAMES.filter(g => !profileGames.some(pg => pg.appId === g.appId)).map(g => (
                  <option key={g.appId} value={g.appId}>{g.name}</option>
                ))}
              </select>
              <input
                placeholder="Или App ID"
                value={addGameId && !ALL_GAMES.some(g => String(g.appId) === addGameId) ? addGameId : ''}
                onChange={(e) => setAddGameId(e.target.value.replace(/\D/g, ''))}
                className="w-24 rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-2 py-1.5 text-center text-sm outline-none"
              />
              <button
                onClick={handleAddGameToProfile}
                disabled={!addGameId}
                className="rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-sm text-[hsl(var(--primary-foreground))] disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>

            {/* Кнопки */}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowProfileModal(false)}
                className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm hover:bg-[hsl(var(--accent))]"
              >
                Отмена
              </button>
              <button
                onClick={handleSaveProfile}
                disabled={!profileName.trim() || profileGames.filter(g => g.weight > 0).length === 0}
                className="rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm text-[hsl(var(--primary-foreground))] disabled:opacity-50"
              >
                {editingProfile ? 'Сохранить' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
