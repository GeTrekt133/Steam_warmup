import { useState, useEffect, useRef } from 'react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Modal, ModalHeader, ModalBody } from '@/components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/Table'
import {
  Upload,
  FileText,
  FolderOpen,
  CheckCircle,
  AlertCircle,
  Users,
  Search,
  Trash2,
  ChevronRight,
  FileKey,
  Globe,
  Package,
  Copy,
  ShieldCheck,
  Pickaxe,
  Gift,
  Wallet,
  Shield,
  RefreshCw,
  Sparkles,
  Mail,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Типы ────────────────────────────────────────────────────

interface Account {
  id: string
  login: string
  password: string
  maFile: boolean        // есть ли привязанный maFile
  maFileName?: string    // имя файла maFile
  sharedSecret?: string  // shared_secret из maFile для генерации 2FA кода
  maFileJson?: string    // полный JSON maFile (для ASF)
  steamId?: string       // Steam ID (SteamID64) аккаунта
  balance?: string       // баланс кошелька Steam (например "123,45 pуб.")
  balanceUsd?: number    // баланс в USD
  addedAt: string        // дата добавления (ISO)
  rank?: number          // ранг аккаунта
  exp?: number           // опыт аккаунта
  cs2Level?: number | null     // уровень профиля CS2 (1-40)
  cs2Xp?: number | null        // текущий XP в CS2
  premierRank?: number | null  // Premier рейтинг
  vacBanned?: boolean | null   // VAC бан в CS2 (null = не проверен)
  status: string         // текущий статус аккаунта (wait, farming, warmup, drop и тд)
  prime?: boolean | null  // CS2 Prime статус (null = не проверен)
  email?: string         // email аккаунта (для привязки Guard)
  emailPassword?: string // пароль от email
  isFarmed: boolean      // аккаунт зафармлен
  isDropCollected: boolean // дроп собран
  dropValue?: number     // сумма дропов в долларах
}

// ─── localStorage хранилище (пока нет backend) ───────────────

const STORAGE_KEY = 'steam_accounts'

function loadAccounts(): Account[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Account[]
    // Миграция: добавляем новые поля для старых аккаунтов
    return parsed.map((a) => ({
      ...a,
      status: a.status === 'wait' ? 'waiting' : (a.status ?? 'waiting'),
      prime: a.prime ?? null,
      cs2Level: a.cs2Level ?? null,
      cs2Xp: a.cs2Xp ?? null,
      premierRank: a.premierRank ?? null,
      vacBanned: a.vacBanned ?? null,
      email: a.email ?? undefined,
      emailPassword: a.emailPassword ?? undefined,
      isFarmed: a.isFarmed ?? false,
      isDropCollected: a.isDropCollected ?? false,
      dropValue: a.dropValue ?? 0,
    }))
  } catch {
    return []
  }
}

function saveAccounts(accounts: Account[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(accounts))
}

// ─── Генерация ID ────────────────────────────────────────────

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

// ─── Steam Guard 2FA код из shared_secret ─────────────────────

const STEAM_CHARS = '23456789BCDFGHJKMNPQRTVWXY'

async function generateSteamGuardCode(sharedSecret: string): Promise<string> {
  // Декодируем base64 shared_secret в ключ
  const keyBytes = Uint8Array.from(atob(sharedSecret), (c) => c.charCodeAt(0))

  // Время: Steam использует 30-секундные интервалы
  const time = Math.floor(Date.now() / 1000 / 30)
  const timeBytes = new Uint8Array(8)
  let t = time
  for (let i = 7; i >= 0; i--) {
    timeBytes[i] = t & 0xff
    t = Math.floor(t / 256)
  }

  // HMAC-SHA1
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-1' }, false, ['sign'])
  const sig = await crypto.subtle.sign('HMAC', key, timeBytes)
  const hash = new Uint8Array(sig)

  // Извлекаем 5-символьный код
  const offset = hash[19] & 0x0f
  let code = ((hash[offset] & 0x7f) << 24) | (hash[offset + 1] << 16) | (hash[offset + 2] << 8) | hash[offset + 3]

  let result = ''
  for (let i = 0; i < 5; i++) {
    result += STEAM_CHARS[code % STEAM_CHARS.length]
    code = Math.floor(code / STEAM_CHARS.length)
  }
  return result
}

// ─── Главный компонент ───────────────────────────────────────

interface ContextMenuState {
  x: number
  y: number
  account: Account
}

export function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>(() => loadAccounts())
  const [search, setSearch] = useState('')
  const [showImportModal, setShowImportModal] = useState(false)
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const contextMenuTimeRef = useRef(0)
  const lastClickedIndexRef = useRef<number | null>(null)

  // Сохраняем при изменении
  useEffect(() => {
    if (accounts.length > 0) {
      saveAccounts(accounts)
    }
  }, [accounts])

  function handleImportDone(newAccounts: Account[]) {
    setAccounts((prev) => {
      const updated = [...prev, ...newAccounts]
      saveAccounts(updated)
      return updated
    })
    setShowImportModal(false)
  }

  function handleDeleteAccount(id: string) {
    setAccounts((prev) => {
      const updated = prev.filter((a) => a.id !== id)
      saveAccounts(updated)
      return updated
    })
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  // Набор ID для массовых действий: если правый клик по выделенному — все выделенные,
  // иначе — только тот аккаунт, по которому кликнули
  function getTargetIds(account: Account): Set<string> {
    if (selectedIds.has(account.id) && selectedIds.size > 1) {
      return new Set(selectedIds)
    }
    return new Set([account.id])
  }

  function handleDeleteSelected() {
    setAccounts((prev) => {
      const updated = prev.filter((a) => !selectedIds.has(a.id))
      saveAccounts(updated)
      return updated
    })
    setSelectedIds(new Set())
  }

  function handleDeleteAll() {
    setAccounts([])
    setSelectedIds(new Set())
    localStorage.removeItem(STORAGE_KEY)
  }

  // ─── Выделение (обычный клик = toggle, Shift = диапазон) ────
  function handleRowClick(idx: number, e: React.MouseEvent) {
    const accountId = filtered[idx].id

    if (e.shiftKey && lastClickedIndexRef.current !== null) {
      // Shift+клик — выделяем диапазон от последнего клика до текущего
      const start = Math.min(lastClickedIndexRef.current, idx)
      const end = Math.max(lastClickedIndexRef.current, idx)
      setSelectedIds((prev) => {
        const next = new Set(prev)
        for (let i = start; i <= end; i++) {
          next.add(filtered[i].id)
        }
        return next
      })
    } else {
      // Обычный клик — добавить/убрать аккаунт (toggle)
      setSelectedIds((prev) => {
        const next = new Set(prev)
        if (next.has(accountId)) {
          next.delete(accountId)
        } else {
          next.add(accountId)
        }
        return next
      })
      lastClickedIndexRef.current = idx
    }
  }

  function toggleCheckbox(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function toggleSelectAll() {
    if (selectedIds.size === filtered.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filtered.map((a) => a.id)))
    }
  }

  // ─── Контекстное меню ──────────────────────────────────────
  // Закрытие при клике вне меню (с защитой от мгновенного закрытия)
  useEffect(() => {
    if (!contextMenu) return

    function handleMouseDown(e: MouseEvent) {
      // Не закрываем если кликнули внутри меню
      const target = e.target as HTMLElement
      if (target.closest('[data-context-menu]')) return
      // Защита от мгновенного закрытия — игнорируем если прошло <100мс
      if (Date.now() - contextMenuTimeRef.current < 100) return
      setContextMenu(null)
    }

    document.addEventListener('mousedown', handleMouseDown, true)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown, true)
    }
  }, [contextMenu])

  function handleContextMenu(e: React.MouseEvent, account: Account) {
    e.preventDefault()
    e.stopPropagation()
    contextMenuTimeRef.current = Date.now()
    setContextMenu({ x: e.clientX, y: e.clientY, account })
  }

  async function handleOpenInBrowser(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    for (const acc of targets) {
      try {
        await api.post('/api/accounts/open-browser-raw', {
          login: acc.login,
          password: acc.password,
          shared_secret: acc.sharedSecret || undefined,
        })
      } catch (e: any) {
        console.error(`[browser] Ошибка для ${acc.login}:`, e.response?.data?.detail || e.message)
      }
    }
    setContextMenu(null)
  }

  function handleCollectDrop(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    for (const acc of targets) {
      console.log(`[drop] Collecting drop for ${acc.login}`)
    }
    setContextMenu(null)
  }

  async function handleParseInfo(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    setContextMenu(null)
    for (const acc of targets) {
      try {
        const res = await api.post('/api/accounts/parse-info', {
          login: acc.login,
          password: acc.password,
          shared_secret: acc.sharedSecret || undefined,
        }, { timeout: 120000 })
        if (res.data.success) {
          setAccounts((prev) => {
            const updated = prev.map((a) =>
              a.id === acc.id ? {
                ...a,
                balance: res.data.balance ?? a.balance,
                balanceUsd: res.data.balance_usd ?? a.balanceUsd,
                prime: res.data.prime ?? a.prime,
              } : a
            )
            saveAccounts(updated)
            return updated
          })
        }
      } catch (e: any) {
        console.error(`[info] Ошибка для ${acc.login}:`, e.response?.data?.detail || e.message)
      }
    }
  }

  // Результаты привязки Steam Guard
  const [guardResults, setGuardResults] = useState<{login: string; success: boolean; revocation_code?: string; error?: string}[] | null>(null)

  // Привязка Steam Guard
  async function handleLinkGuard(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    // Фильтруем: только аккаунты с email и emailPassword, без maFile
    const eligible = targets.filter((a) => a.email && a.emailPassword && !a.maFile)
    if (eligible.length === 0) return
    setContextMenu(null)

    try {
      const res = await api.post('/api/accounts/link-guard-batch', {
        accounts: eligible.map((a) => ({
          login: a.login,
          password: a.password,
          email: a.email,
          email_password: a.emailPassword,
        })),
      }, { timeout: 300000 })

      const results: {login: string; success: boolean; revocation_code?: string; error?: string; shared_secret?: string; mafile_json?: string; steam_id?: string}[] = res.data.results || []

      // Обновляем аккаунты в стейте
      setAccounts((prev) => {
        const updated = prev.map((a) => {
          const result = results.find((r) => r.login === a.login)
          if (result?.success) {
            return {
              ...a,
              maFile: true,
              sharedSecret: result.shared_secret || a.sharedSecret,
              maFileJson: result.mafile_json || a.maFileJson,
              steamId: result.steam_id || a.steamId,
            }
          }
          return a
        })
        saveAccounts(updated)
        return updated
      })

      setGuardResults(results.map((r) => ({
        login: r.login,
        success: r.success,
        revocation_code: r.revocation_code,
        error: r.error,
      })))
    } catch (e: any) {
      setGuardResults(eligible.map((a) => ({
        login: a.login,
        success: false,
        error: e.response?.data?.detail || e.message || 'Ошибка запроса',
      })))
    }
  }

  // Проверка Community Badge
  const [badgeResult, setBadgeResult] = useState<{ login: string; badge_level: number; tasks_completed: number; tasks_total: number; tasks: { name: string; completed: boolean }[] } | null>(null)

  async function handleCheckBadge(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    setContextMenu(null)
    setBadgeResult(null)
    for (const acc of targets) {
      try {
        const res = await api.post('/api/accounts/check-badge', {
          login: acc.login,
          password: acc.password,
          shared_secret: acc.sharedSecret || undefined,
        }, { timeout: 120000 })
        if (res.data.success) {
          setBadgeResult({
            login: acc.login,
            badge_level: res.data.badge_level,
            tasks_completed: res.data.tasks_completed,
            tasks_total: res.data.tasks_total,
            tasks: res.data.tasks || [],
          })
        }
      } catch (e: any) {
        console.error(`[badge] Ошибка для ${acc.login}:`, e.response?.data?.detail || e.message)
      }
    }
  }

  // Получение CS2 профиля через Game Coordinator
  async function handleFetchCS2Profile(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    setContextMenu(null)
    for (const acc of targets) {
      try {
        const res = await api.post('/api/accounts/cs2-profile', {
          login: acc.login,
          password: acc.password,
          shared_secret: acc.sharedSecret || undefined,
        }, { timeout: 45000 })
        console.log('[cs2-profile] ответ:', res.data)
        if (res.data.success) {
          setAccounts((prev) => {
            const updated = prev.map((a) =>
              a.id === acc.id ? {
                ...a,
                cs2Level: res.data.player_level,
                cs2Xp: res.data.player_cur_xp,
                vacBanned: res.data.vac_banned > 0,
                status: a.status === 'in_game' ? 'waiting' : a.status,
              } : a
            )
            saveAccounts(updated)
            return updated
          })
        } else if (res.data.error?.includes('LoggedInElsewhere')) {
          setAccounts((prev) => {
            const updated = prev.map((a) =>
              a.id === acc.id ? { ...a, status: 'in_game' } : a
            )
            saveAccounts(updated)
            return updated
          })
        }
      } catch (e: any) {
        console.error(`[cs2] Ошибка для ${acc.login}:`, e.response?.data?.detail || e.message)
      }
    }
  }

  // Переключение статуса «Зафармлен»
  function handleToggleFarmed(account: Account) {
    const ids = getTargetIds(account)
    setAccounts((prev) => {
      const updated = prev.map((a) =>
        ids.has(a.id) ? { ...a, isFarmed: !a.isFarmed } : a
      )
      saveAccounts(updated)
      return updated
    })
    setContextMenu(null)
  }

  // Переключение статуса «Дроп собран»
  function handleToggleDropCollected(account: Account) {
    const ids = getTargetIds(account)
    setAccounts((prev) => {
      const updated = prev.map((a) =>
        ids.has(a.id) ? { ...a, isDropCollected: !a.isDropCollected } : a
      )
      saveAccounts(updated)
      return updated
    })
    setContextMenu(null)
  }

  // Удаление через контекстное меню (массовое)
  function handleDeleteFromMenu(account: Account) {
    const ids = getTargetIds(account)
    setAccounts((prev) => {
      const updated = prev.filter((a) => !ids.has(a.id))
      saveAccounts(updated)
      return updated
    })
    setSelectedIds((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.delete(id))
      return next
    })
    setContextMenu(null)
  }

  // Фильтрация по поиску
  const filtered = accounts.filter((a) =>
    a.login.toLowerCase().includes(search.toLowerCase())
  )

  const allSelected = filtered.length > 0 && selectedIds.size === filtered.length

  // Если нет аккаунтов — показываем полноэкранный мастер импорта
  if (accounts.length === 0 && !showImportModal) {
    return <ImportWizard onDone={handleImportDone} />
  }

  // Сброс выделения при клике по пустому пространству
  function handlePageClick(e: React.MouseEvent) {
    const target = e.target as HTMLElement
    // Если клик не попал по строке таблицы, кнопке или чекбоксу — сбрасываем
    if (!target.closest('tr') && !target.closest('button') && !target.closest('input') && !target.closest('[data-context-menu]')) {
      setSelectedIds(new Set())
    }
  }

  // Есть аккаунты — таблица
  return (
    <div className="flex flex-col h-full p-6" onClick={handlePageClick}>
      {/* Заголовок + действия */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Users className="h-6 w-6 text-[hsl(var(--primary))]" />
            Аккаунты
          </h1>
          <p className="text-sm text-[hsl(var(--muted-foreground))] mt-0.5">
            {accounts.length} {pluralAccounts(accounts.length)} загружено
            {selectedIds.size > 0 && (
              <span className="text-[hsl(var(--primary))] ml-2">
                ({selectedIds.size} выбрано)
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const firstSelected = accounts.find((a) => selectedIds.has(a.id))
                  if (firstSelected) handleParseInfo(firstSelected)
                }}
              >
                <RefreshCw className="h-4 w-4" />
                Обновить прайм и баланс ({selectedIds.size})
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const firstSelected = accounts.find((a) => selectedIds.has(a.id))
                  if (firstSelected) handleFetchCS2Profile(firstSelected)
                }}
              >
                <ShieldCheck className="h-4 w-4" />
                CS2 профиль ({selectedIds.size})
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const firstSelected = accounts.find((a) => selectedIds.has(a.id))
                  if (firstSelected) handleLinkGuard(firstSelected)
                }}
              >
                <Shield className="h-4 w-4" />
                Привязать Guard ({selectedIds.size})
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={handleDeleteSelected}
              >
                <Trash2 className="h-4 w-4" />
                Удалить выбранные ({selectedIds.size})
              </Button>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowImportModal(true)}
          >
            <Upload className="h-4 w-4" />
            Импорт
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={handleDeleteAll}
          >
            <Trash2 className="h-4 w-4" />
            Очистить всё
          </Button>
        </div>
      </div>

      {/* Поиск */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[hsl(var(--muted-foreground))]" />
        <input
          type="text"
          placeholder="Поиск по логину..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-sm rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] pl-9 pr-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] placeholder:text-[hsl(var(--muted-foreground)/0.5)]"
        />
      </div>

      {/* Таблица */}
      <div className="flex-1 overflow-auto rounded-lg border border-[hsl(var(--border))]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  className="h-4 w-4 rounded border-[hsl(var(--input))] accent-[hsl(var(--primary))] cursor-pointer"
                />
              </TableHead>
              <TableHead className="w-10">#</TableHead>
              <TableHead>Логин</TableHead>
              <TableHead className="w-28">Статус</TableHead>
              <TableHead className="w-28">Steam ID</TableHead>
              <TableHead className="w-32">maFile</TableHead>
              <TableHead className="w-28">Баланс</TableHead>
              <TableHead className="w-20 text-center">Прайм</TableHead>
              <TableHead className="w-16 text-center">CS2 Lvl</TableHead>
              <TableHead className="w-20 text-center">CS2 XP</TableHead>
              <TableHead className="w-16 text-center">VAC</TableHead>
              <TableHead className="w-28 text-center">Зафармлен</TableHead>
              <TableHead className="w-28 text-center">Дроп собран</TableHead>
              <TableHead className="w-40">Добавлен</TableHead>
              <TableHead className="w-20">Действия</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((account, idx) => (
              <TableRow
                key={account.id}
                onClick={(e) => handleRowClick(idx, e)}
                onContextMenu={(e) => handleContextMenu(e, account)}
                className={cn(
                  'cursor-default select-none',
                  selectedIds.has(account.id) && 'bg-[hsl(var(--primary)/0.08)]',
                  !selectedIds.has(account.id) && account.isFarmed && account.isDropCollected && 'bg-emerald-500/10',
                  !selectedIds.has(account.id) && account.isFarmed && !account.isDropCollected && 'bg-amber-500/8',
                  !selectedIds.has(account.id) && !account.isFarmed && account.isDropCollected && 'bg-emerald-500/6',
                )}
              >
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(account.id)}
                    onChange={() => toggleCheckbox(account.id)}
                    className="h-4 w-4 rounded border-[hsl(var(--input))] accent-[hsl(var(--primary))] cursor-pointer"
                  />
                </TableCell>
                <TableCell className="text-[hsl(var(--muted-foreground))]">
                  {idx + 1}
                </TableCell>
                <TableCell className="font-medium">{account.login}</TableCell>
                <TableCell className="text-sm">
                  {account.status === 'in_game' ? (
                    <span className="text-blue-400">В игре</span>
                  ) : (
                    <span className="text-[hsl(var(--muted-foreground))]">{account.status}</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-[hsl(var(--muted-foreground))] font-mono">
                  {account.steamId || '—'}
                </TableCell>
                <TableCell>
                  {account.maFile ? (
                    <span className="inline-flex items-center gap-1 text-[hsl(var(--success))] text-xs font-medium">
                      <CheckCircle className="h-3.5 w-3.5" />
                      Есть
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[hsl(var(--muted-foreground))] text-xs">
                      <AlertCircle className="h-3.5 w-3.5" />
                      Нет
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-xs font-mono">
                  {account.balance ? (
                    <div>
                      <div>{account.balance}</div>
                      {account.balanceUsd != null && (
                        <div className="text-[hsl(var(--muted-foreground))]">${account.balanceUsd.toFixed(2)}</div>
                      )}
                    </div>
                  ) : '—'}
                </TableCell>
                <TableCell className="text-center text-sm">
                  {account.prime === true && (
                    <span className="text-emerald-400" title="Prime активен">&#10003;</span>
                  )}
                  {account.prime === false && (
                    <span className="text-red-400" title="Prime не куплен">&#10007;</span>
                  )}
                  {(account.prime == null) && (
                    <span className="text-[hsl(var(--muted-foreground))]" title="Не проверено">&mdash;</span>
                  )}
                </TableCell>
                <TableCell className="text-center text-sm">
                  {account.cs2Level != null ? (
                    <span>{account.cs2Level}</span>
                  ) : (
                    <span className="text-[hsl(var(--muted-foreground))]">&mdash;</span>
                  )}
                </TableCell>
                <TableCell className="text-center text-sm">
                  {account.cs2Xp != null ? (
                    <span>{Math.max(0, account.cs2Xp - 327680000).toLocaleString()}</span>
                  ) : (
                    <span className="text-[hsl(var(--muted-foreground))]">&mdash;</span>
                  )}
                </TableCell>
                <TableCell className="text-center text-sm">
                  {account.vacBanned === true && (
                    <span className="text-red-500 font-bold" title="VAC бан в CS2">VAC</span>
                  )}
                  {account.vacBanned === false && (
                    <span className="text-emerald-400" title="Нет VAC бана">Чист</span>
                  )}
                  {(account.vacBanned == null) && (
                    <span className="text-[hsl(var(--muted-foreground))]">&mdash;</span>
                  )}
                </TableCell>
                <TableCell className="text-center">
                  <input
                    type="checkbox"
                    checked={account.isFarmed}
                    readOnly
                    className="h-4 w-4 rounded accent-amber-500 pointer-events-none"
                    title={account.isFarmed ? 'Зафармлен' : 'Не зафармлен'}
                  />
                </TableCell>
                <TableCell className="text-center">
                  <input
                    type="checkbox"
                    checked={account.isDropCollected}
                    readOnly
                    className="h-4 w-4 rounded accent-emerald-500 pointer-events-none"
                    title={account.isDropCollected ? 'Дроп собран' : 'Дроп не собран'}
                  />
                </TableCell>
                <TableCell className="text-[hsl(var(--muted-foreground))] text-xs">
                  {new Date(account.addedAt).toLocaleDateString('ru-RU', {
                    day: '2-digit',
                    month: '2-digit',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </TableCell>
                <TableCell>
                  <button
                    onClick={() => handleDeleteAccount(account.id)}
                    className="rounded-md p-1 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.1)] transition-colors"
                    title="Удалить"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={15} className="text-center py-8 text-[hsl(var(--muted-foreground))]">
                  Ничего не найдено
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Контекстное меню */}
      {contextMenu && (
        <AccountContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          account={contextMenu.account}
          allTargets={
            selectedIds.has(contextMenu.account.id) && selectedIds.size > 1
              ? accounts.filter((a) => selectedIds.has(a.id))
              : [contextMenu.account]
          }
          onClose={() => setContextMenu(null)}
          onOpenBrowser={handleOpenInBrowser}
          onParseInfo={handleParseInfo}
          onFetchCS2Profile={handleFetchCS2Profile}
          onCheckBadge={handleCheckBadge}
          onCollectDrop={handleCollectDrop}
          onLinkGuard={handleLinkGuard}
          onToggleFarmed={handleToggleFarmed}
          onToggleDropCollected={handleToggleDropCollected}
          onDelete={handleDeleteFromMenu}
        />
      )}

      {/* Модалка результата проверки бейджа */}
      {badgeResult && (
        <Modal open={true} onClose={() => setBadgeResult(null)} className="max-w-lg">
          <ModalHeader onClose={() => setBadgeResult(null)}>
            Community Badge — {badgeResult.login}
          </ModalHeader>
          <ModalBody>
            <div className="space-y-3">
              <div className="flex items-center gap-4 text-sm">
                <div>
                  <span className="text-[hsl(var(--muted-foreground))]">Уровень бейджа: </span>
                  <span className="font-bold text-amber-400">{badgeResult.badge_level || 'Нет'}</span>
                </div>
                <div>
                  <span className="text-[hsl(var(--muted-foreground))]">Задачи: </span>
                  <span className="font-bold">{badgeResult.tasks_completed}/{badgeResult.tasks_total}</span>
                </div>
              </div>
              {badgeResult.tasks.length > 0 && (
                <div className="space-y-1 max-h-64 overflow-y-auto">
                  {badgeResult.tasks.map((task, i) => (
                    <div key={i} className={cn(
                      'flex items-center gap-2 text-sm px-2 py-1 rounded',
                      task.completed ? 'text-emerald-400' : 'text-[hsl(var(--muted-foreground))]'
                    )}>
                      <span>{task.completed ? '✓' : '✗'}</span>
                      <span>{task.name}</span>
                    </div>
                  ))}
                </div>
              )}
              {badgeResult.tasks.length === 0 && badgeResult.tasks_total === 0 && (
                <p className="text-sm text-[hsl(var(--muted-foreground))]">
                  Бейдж ещё не начат или не удалось спарсить задачи
                </p>
              )}
            </div>
          </ModalBody>
        </Modal>
      )}

      {/* Модалка результатов привязки Steam Guard */}
      {guardResults && (
        <Modal open={true} onClose={() => setGuardResults(null)} className="max-w-lg">
          <ModalHeader onClose={() => setGuardResults(null)}>
            Привязка Steam Guard
          </ModalHeader>
          <ModalBody>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {guardResults.map((r, i) => (
                <div
                  key={i}
                  className={cn(
                    'flex items-center gap-2 text-sm px-3 py-2 rounded-md',
                    r.success
                      ? 'bg-[hsl(var(--success)/0.1)] text-emerald-400'
                      : 'bg-[hsl(var(--destructive)/0.1)] text-red-400'
                  )}
                >
                  <span>{r.success ? '\u2713' : '\u2717'}</span>
                  <span className="font-medium">{r.login}</span>
                  <span className="text-xs text-[hsl(var(--muted-foreground))] ml-auto">
                    {r.success && r.revocation_code
                      ? `Код отмены: ${r.revocation_code}`
                      : r.error || ''}
                  </span>
                </div>
              ))}
            </div>
          </ModalBody>
        </Modal>
      )}

      {/* Модалка импорта (для существующих аккаунтов) */}
      <Modal
        open={showImportModal}
        onClose={() => setShowImportModal(false)}
        className="max-w-2xl"
      >
        <ModalHeader onClose={() => setShowImportModal(false)}>
          Импорт аккаунтов
        </ModalHeader>
        <ModalBody>
          <ImportWizardContent
            onDone={handleImportDone}
            onCancel={() => setShowImportModal(false)}
            existingAccounts={accounts}
          />
        </ModalBody>
      </Modal>
    </div>
  )
}

// ─── Контекстное меню аккаунта ────────────────────────────────

function AccountContextMenu({
  x,
  y,
  account,
  allTargets,
  onClose,
  onOpenBrowser,
  onParseInfo,
  onFetchCS2Profile,
  onCheckBadge,
  onCollectDrop,
  onLinkGuard,
  onToggleFarmed,
  onToggleDropCollected,
  onDelete,
}: {
  x: number
  y: number
  account: Account
  allTargets: Account[]
  onClose: () => void
  onOpenBrowser: (acc: Account) => void
  onParseInfo: (acc: Account) => void
  onFetchCS2Profile: (acc: Account) => void
  onCheckBadge: (acc: Account) => void
  onCollectDrop: (acc: Account) => void
  onLinkGuard: (acc: Account) => void
  onToggleFarmed: (acc: Account) => void
  onToggleDropCollected: (acc: Account) => void
  onDelete: (acc: Account) => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })
  const [copiedField, setCopiedField] = useState<string | null>(null)

  // Корректируем позицию, чтобы меню не вылезало за экран
  useEffect(() => {
    if (!menuRef.current) return
    const rect = menuRef.current.getBoundingClientRect()
    let newX = x
    let newY = y
    if (x + rect.width > window.innerWidth) {
      newX = window.innerWidth - rect.width - 8
    }
    if (y + rect.height > window.innerHeight) {
      newY = window.innerHeight - rect.height - 8
    }
    setPos({ x: newX, y: newY })
  }, [x, y])

  function copyToClipboard(text: string, field: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedField(field)
      setTimeout(() => {
        onClose()
      }, 600)
    })
  }

  type MenuItem =
    | { label: string; icon: typeof Globe; onClick: () => void; destructive?: boolean; disabled?: boolean; active?: boolean }
    | { type: 'separator' }

  const multi = allTargets.length > 1

  const items: MenuItem[] = [
    {
      label: multi ? `Копировать логины (${allTargets.length})` : 'Копировать логин',
      icon: Copy,
      onClick: () => copyToClipboard(allTargets.map((a) => a.login).join('\n'), 'login'),
    },
    {
      label: multi ? `Копировать пароли (${allTargets.length})` : 'Копировать пароль',
      icon: Copy,
      onClick: () => copyToClipboard(allTargets.map((a) => a.password).join('\n'), 'password'),
    },
    {
      label: multi ? `Копировать логин:пароль (${allTargets.length})` : 'Копировать логин:пароль',
      icon: Copy,
      onClick: () => copyToClipboard(allTargets.map((a) => `${a.login}:${a.password}`).join('\n'), 'loginpass'),
    },
    {
      label: 'Копировать 2FA',
      icon: ShieldCheck,
      onClick: async () => {
        const withSecret = allTargets.filter((a) => a.sharedSecret)
        const codes = await Promise.all(
          withSecret.map(async (a) => {
            const code = await generateSteamGuardCode(a.sharedSecret!)
            return withSecret.length > 1 ? `${a.login}:${code}` : code
          })
        )
        copyToClipboard(codes.join('\n'), '2fa')
      },
      disabled: !allTargets.some((a) => a.sharedSecret),
    },
    { type: 'separator' },
    {
      label: 'Открыть в браузере',
      icon: Globe,
      onClick: () => onOpenBrowser(account),
    },
    {
      label: multi ? `Обновить прайм и баланс (${allTargets.length})` : 'Обновить прайм и баланс',
      icon: RefreshCw,
      onClick: () => onParseInfo(account),
    },
    {
      label: multi ? `CS2 профиль (${allTargets.length})` : 'CS2 профиль',
      icon: ShieldCheck,
      onClick: () => onFetchCS2Profile(account),
    },
    {
      label: 'Проверить бейдж',
      icon: Sparkles,
      onClick: () => onCheckBadge(account),
    },
    {
      label: 'Собрать дроп',
      icon: Package,
      onClick: () => onCollectDrop(account),
    },
    {
      label: multi ? `Привязать Guard (${allTargets.length})` : 'Привязать Guard',
      icon: Shield,
      onClick: () => onLinkGuard(account),
    },
    { type: 'separator' },
    {
      label: account.isFarmed ? 'Снять отметку «Зафармлен»' : 'Аккаунт зафармлен',
      icon: Pickaxe,
      onClick: () => onToggleFarmed(account),
      active: account.isFarmed,
    },
    {
      label: account.isDropCollected ? 'Снять отметку «Дроп собран»' : 'Дроп собран',
      icon: Gift,
      onClick: () => onToggleDropCollected(account),
      active: account.isDropCollected,
    },
    { type: 'separator' },
    {
      label: 'Удалить',
      icon: Trash2,
      onClick: () => onDelete(account),
      destructive: true,
    },
  ]

  return (
    <div
      ref={menuRef}
      data-context-menu
      className="fixed z-[999] min-w-[220px] rounded-lg border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] shadow-xl py-1"
      style={{ left: pos.x, top: pos.y }}
    >
      {/* Заголовок с логином / количеством */}
      <div className="px-3 py-1.5 border-b border-[hsl(var(--border))] mb-1">
        <span className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
          {multi
            ? `${allTargets.length} ${pluralAccounts(allTargets.length)} выбрано`
            : account.login
          }
        </span>
      </div>

      {items.map((item, i) => {
        if ('type' in item) {
          return (
            <div key={i} className="my-1 border-t border-[hsl(var(--border))]" />
          )
        }

        const isCopied =
          (item.label === 'Копировать логин' && copiedField === 'login') ||
          (item.label === 'Копировать пароль' && copiedField === 'password') ||
          (item.label === 'Копировать логин:пароль' && copiedField === 'loginpass') ||
          (item.label === 'Копировать 2FA' && copiedField === '2fa')

        return (
          <button
            key={i}
            onClick={item.onClick}
            disabled={item.disabled}
            className={cn(
              'flex items-center gap-2.5 w-full px-3 py-1.5 text-sm text-left transition-colors',
              item.disabled && 'opacity-40 cursor-not-allowed',
              !item.disabled && !item.destructive && 'text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]',
              !item.disabled && item.destructive && 'text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.1)]',
              isCopied && 'text-[hsl(var(--success))]',
              item.active && 'text-emerald-400'
            )}
          >
            {isCopied ? (
              <CheckCircle className="h-4 w-4 flex-shrink-0" />
            ) : item.active ? (
              <CheckCircle className="h-4 w-4 flex-shrink-0 text-emerald-400" />
            ) : (
              <item.icon className="h-4 w-4 flex-shrink-0" />
            )}
            {isCopied ? 'Скопировано!' : item.label}
          </button>
        )
      })}
    </div>
  )
}

// ─── Ячейка пароля (скрыт/показать) ─────────────────────────

// ─── Мастер импорта (полноэкранный) ─────────────────────────

interface ImportWizardProps {
  onDone: (accounts: Account[]) => void
}

function ImportWizard({ onDone }: ImportWizardProps) {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="w-full max-w-2xl">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center h-16 w-16 rounded-2xl bg-[hsl(var(--primary)/0.15)] mb-4">
            <Users className="h-8 w-8 text-[hsl(var(--primary))]" />
          </div>
          <h1 className="text-2xl font-bold mb-2">Добавьте свои Steam-аккаунты</h1>
          <p className="text-[hsl(var(--muted-foreground))] max-w-md mx-auto">
            Для начала работы импортируйте аккаунты из текстового файла.
            После этого вы сможете привязать maFile для каждого аккаунта.
          </p>
        </div>

        <ImportWizardContent onDone={onDone} existingAccounts={[]} />
      </div>
    </div>
  )
}

// ─── Содержимое мастера (используется и на экране, и в модалке) ─

type WizardStep = 'txt' | 'mafiles' | 'done'

interface ImportWizardContentProps {
  onDone: (accounts: Account[]) => void
  onCancel?: () => void
  existingAccounts: Account[]
}

function ImportWizardContent({ onDone, onCancel, existingAccounts }: ImportWizardContentProps) {
  const [step, setStep] = useState<WizardStep>('txt')
  const [parsedAccounts, setParsedAccounts] = useState<Account[]>([])
  const [txtError, setTxtError] = useState('')
  const [maResult, setMaResult] = useState<{ matched: number; total: number } | null>(null)

  const [emailResult, setEmailResult] = useState<{ matched: number; total: number } | null>(null)

  const txtInputRef = useRef<HTMLInputElement>(null)
  const maInputRef = useRef<HTMLInputElement>(null)
  const emailInputRef = useRef<HTMLInputElement>(null)

  // Проверяем, доступен ли Electron API
  const isElectron = !!(window as any).electronAPI?.openFile

  // ─── Общая обработка содержимого TXT ─────
  function processTxtContent(content: string) {
    setTxtError('')
    const { accounts, totalInFile, skippedDuplicates } = parseTxtAccounts(content, existingAccounts)

    if (totalInFile === 0) {
      setTxtError('Файл пуст или не содержит строк в формате логин:пароль')
      return
    }

    if (accounts.length === 0 && skippedDuplicates > 0) {
      setTxtError(`Все ${skippedDuplicates} ${pluralAccounts(skippedDuplicates)} из файла уже добавлены`)
      return
    }

    setParsedAccounts(accounts)
    setStep('mafiles')
  }

  // ─── Шаг 1: Импорт TXT ─────
  async function handleTxtClick() {
    if (isElectron) {
      // Electron: нативный диалог
      try {
        const electronAPI = (window as any).electronAPI
        const result = await electronAPI.openFile({
          title: 'Выберите TXT файл с аккаунтами',
          filters: [{ name: 'Text Files', extensions: ['txt'] }],
          properties: ['openFile'],
        })
        if (result.canceled || !result.filePaths?.length) return
        const content = await electronAPI.readTextFile(result.filePaths[0])
        processTxtContent(content)
      } catch {
        setTxtError('Ошибка чтения файла')
      }
    } else {
      // Браузер: скрытый input
      txtInputRef.current?.click()
    }
  }

  function handleTxtFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (ev) => {
      processTxtContent(ev.target?.result as string)
    }
    reader.onerror = () => setTxtError('Ошибка чтения файла')
    reader.readAsText(file, 'utf-8')
    e.target.value = ''
  }

  // ─── Общая обработка maFile содержимого ─────
  function processMaFileContent(content: string, updatedAccounts: Account[]): boolean {
    try {
      const json = JSON.parse(content)
      const accountName: string | undefined = json.account_name

      if (accountName) {
        const account = updatedAccounts.find(
          (a) => a.login.toLowerCase() === accountName.toLowerCase() && !a.maFile
        )
        if (account) {
          account.maFile = true
          account.maFileName = accountName + '.maFile'
          if (json.shared_secret) {
            account.sharedSecret = json.shared_secret
          }
          account.maFileJson = content
          if (json.Session?.SteamID) {
            account.steamId = String(json.Session.SteamID)
          }
          return true
        }
      }
    } catch {
      // Битый maFile
    }
    return false
  }

  // ─── Шаг 2: Импорт maFiles ─────
  async function handleMaClick() {
    if (isElectron) {
      // Electron: нативный диалог
      try {
        const electronAPI = (window as any).electronAPI
        const result = await electronAPI.openFile({
          title: 'Выберите maFile файлы',
          filters: [{ name: 'maFile', extensions: ['maFile', 'mafile'] }],
          properties: ['openFile', 'multiSelections'],
        })
        if (result.canceled || !result.filePaths?.length) return

        let matched = 0
        const total = result.filePaths.length
        const updatedAccounts = [...parsedAccounts]

        for (const filePath of result.filePaths) {
          const content = await electronAPI.readFile(filePath)
          if (processMaFileContent(content, updatedAccounts)) matched++
        }

        setParsedAccounts([...updatedAccounts])
        setMaResult({ matched, total })
        setStep('done')
      } catch {
        // Диалог отменён или ошибка
      }
    } else {
      // Браузер: скрытый input
      maInputRef.current?.click()
    }
  }

  function handleMaFilesChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return

    let matched = 0
    let processed = 0
    const total = files.length
    const updatedAccounts = [...parsedAccounts]

    for (let i = 0; i < files.length; i++) {
      const reader = new FileReader()
      reader.onload = (ev) => {
        processed++
        if (processMaFileContent(ev.target?.result as string, updatedAccounts)) matched++

        if (processed === total) {
          setParsedAccounts([...updatedAccounts])
          setMaResult({ matched, total })
          setStep('done')
        }
      }
      reader.readAsText(files[i], 'utf-8')
    }
    e.target.value = ''
  }

  // ─── Импорт email TXT (альтернатива maFile) ─────
  function processEmailTxtContent(content: string) {
    const lines = content.split(/\r?\n/)
    let matched = 0
    let total = 0
    const updatedAccounts = [...parsedAccounts]

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#') || trimmed.startsWith('//')) continue

      // Формат: login:email:email_password
      const parts = trimmed.split(':')
      if (parts.length < 3) continue

      const login = parts[0].trim()
      const email = parts[1].trim()
      const emailPassword = parts.slice(2).join(':').trim()

      if (!login || !email || !emailPassword) continue
      total++

      const account = updatedAccounts.find(
        (a) => a.login.toLowerCase() === login.toLowerCase()
      )
      if (account) {
        account.email = email
        account.emailPassword = emailPassword
        matched++
      }
    }

    setParsedAccounts([...updatedAccounts])
    setEmailResult({ matched, total })
  }

  async function handleEmailTxtClick() {
    if (isElectron) {
      try {
        const electronAPI = (window as any).electronAPI
        const result = await electronAPI.openFile({
          title: 'Выберите TXT файл с email',
          filters: [{ name: 'Text Files', extensions: ['txt'] }],
          properties: ['openFile'],
        })
        if (result.canceled || !result.filePaths?.length) return
        const content = await electronAPI.readTextFile(result.filePaths[0])
        processEmailTxtContent(content)
      } catch {
        // Диалог отменён или ошибка
      }
    } else {
      emailInputRef.current?.click()
    }
  }

  function handleEmailFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (ev) => {
      processEmailTxtContent(ev.target?.result as string)
    }
    reader.readAsText(file, 'utf-8')
    e.target.value = ''
  }

  // Пропуск шага maFiles
  function handleSkipMaFiles() {
    setStep('done')
  }

  // Завершение
  function handleFinish() {
    onDone(parsedAccounts)
  }

  // ─── Рендер по шагам ────────────────────────────────────

  return (
    <div>
      {/* Скрытые файловые инпуты (fallback для браузера) */}
      {!isElectron && (
        <>
          <input
            ref={txtInputRef}
            type="file"
            accept=".txt"
            className="hidden"
            onChange={handleTxtFileChange}
          />
          <input
            ref={maInputRef}
            type="file"
            accept=".maFile,.mafile"
            multiple
            className="hidden"
            onChange={handleMaFilesChange}
          />
          <input
            ref={emailInputRef}
            type="file"
            accept=".txt"
            className="hidden"
            onChange={handleEmailFileChange}
          />
        </>
      )}

      {/* Индикатор шагов */}
      <div className="flex items-center gap-2 mb-6">
        <StepIndicator num={1} label="TXT файл" active={step === 'txt'} done={step !== 'txt'} />
        <ChevronRight className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
        <StepIndicator num={2} label="maFile" active={step === 'mafiles'} done={step === 'done'} />
        <ChevronRight className="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
        <StepIndicator num={3} label="Готово" active={step === 'done'} done={false} />
      </div>

      {/* Шаг 1: TXT */}
      {step === 'txt' && (
        <div className="rounded-lg border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] p-6">
          <div className="flex items-start gap-4">
            <div className="h-10 w-10 rounded-lg bg-[hsl(var(--primary)/0.15)] flex items-center justify-center flex-shrink-0">
              <FileText className="h-5 w-5 text-[hsl(var(--primary))]" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold mb-1">Импорт из TXT файла</h3>
              <p className="text-sm text-[hsl(var(--muted-foreground))] mb-4">
                Выберите текстовый файл где каждая строка содержит аккаунт в формате:
              </p>
              <div className="rounded-md bg-[hsl(var(--background))] border border-[hsl(var(--border))] p-3 mb-4 font-mono text-xs text-[hsl(var(--muted-foreground))]">
                <div>login1:password1</div>
                <div>login2:password2</div>
                <div>login3:password3</div>
              </div>

              {txtError && (
                <div className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2 mb-4 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 flex-shrink-0" />
                  {txtError}
                </div>
              )}

              <div className="flex gap-2">
                <Button onClick={handleTxtClick}>
                  <Upload className="h-4 w-4" />
                  Выбрать файл
                </Button>
                {onCancel && (
                  <Button variant="ghost" onClick={onCancel}>
                    Отмена
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Шаг 2: maFiles */}
      {step === 'mafiles' && (
        <div className="space-y-4">
          {/* Результат импорта TXT */}
          <div className="rounded-lg border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.05)] p-4 flex items-center gap-3">
            <CheckCircle className="h-5 w-5 text-[hsl(var(--success))] flex-shrink-0" />
            <div>
              <p className="text-sm font-medium">
                Импортировано {parsedAccounts.length} {pluralAccounts(parsedAccounts.length)}
              </p>
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                Теперь привяжите maFile для двухфакторной аутентификации
              </p>
            </div>
          </div>

          {/* Выбор maFiles */}
          <div className="rounded-lg border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] p-6">
            <div className="flex items-start gap-4">
              <div className="h-10 w-10 rounded-lg bg-[hsl(var(--warning)/0.15)] flex items-center justify-center flex-shrink-0">
                <FileKey className="h-5 w-5 text-[hsl(var(--warning))]" />
              </div>
              <div className="flex-1">
                <h3 className="font-semibold mb-1">Импорт maFile</h3>
                <p className="text-sm text-[hsl(var(--muted-foreground))] mb-4">
                  Выберите .maFile файлы. Программа автоматически прочитает каждый файл,
                  найдёт <code className="text-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.1)] px-1 rounded">account_name</code> и
                  привяжет maFile к соответствующему аккаунту.
                </p>

                <div className="flex gap-2">
                  <Button onClick={handleMaClick}>
                    <FolderOpen className="h-4 w-4" />
                    Выбрать файлы
                  </Button>
                  <Button variant="outline" onClick={handleEmailTxtClick}>
                    <Mail className="h-4 w-4" />
                    Импорт email
                  </Button>
                  <Button variant="ghost" onClick={handleSkipMaFiles}>
                    Пропустить
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Результат импорта email */}
          {emailResult && (
            <div className="rounded-lg border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.05)] p-4 flex items-center gap-3">
              <Mail className="h-5 w-5 text-[hsl(var(--success))] flex-shrink-0" />
              <div>
                <p className="text-sm font-medium">
                  Email привязан к {emailResult.matched} из {emailResult.total} {pluralAccounts(emailResult.total)}
                </p>
                <p className="text-xs text-[hsl(var(--muted-foreground))]">
                  Формат файла: login:email:email_password
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Шаг 3: Готово */}
      {step === 'done' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.05)] p-6 text-center">
            <CheckCircle className="h-10 w-10 text-[hsl(var(--success))] mx-auto mb-3" />
            <h3 className="text-lg font-semibold mb-1">Импорт завершён!</h3>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              Загружено {parsedAccounts.length} {pluralAccounts(parsedAccounts.length)}
              {maResult && (
                <span>
                  , привязано {maResult.matched} из {maResult.total} maFile
                </span>
              )}
            </p>
          </div>

          {/* Превью таблицы */}
          <div className="rounded-lg border border-[hsl(var(--border))] overflow-hidden max-h-48 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Логин</TableHead>
                  <TableHead className="w-24">maFile</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {parsedAccounts.map((acc) => (
                  <TableRow key={acc.id}>
                    <TableCell className="font-medium text-sm">{acc.login}</TableCell>
                    <TableCell>
                      {acc.maFile ? (
                        <span className="text-[hsl(var(--success))] text-xs">Есть</span>
                      ) : (
                        <span className="text-[hsl(var(--muted-foreground))] text-xs">Нет</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex justify-end gap-2">
            {onCancel && (
              <Button variant="ghost" onClick={onCancel}>
                Отмена
              </Button>
            )}
            <Button onClick={handleFinish}>
              <CheckCircle className="h-4 w-4" />
              Готово
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Индикатор шага ──────────────────────────────────────────

function StepIndicator({
  num,
  label,
  active,
  done,
}: {
  num: number
  label: string
  active: boolean
  done: boolean
}) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={cn(
          'h-6 w-6 rounded-full flex items-center justify-center text-xs font-bold transition-colors',
          active && 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]',
          done && 'bg-[hsl(var(--success))] text-[hsl(var(--success-foreground))]',
          !active && !done && 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
        )}
      >
        {done ? <CheckCircle className="h-3.5 w-3.5" /> : num}
      </div>
      <span
        className={cn(
          'text-sm',
          active ? 'font-medium text-[hsl(var(--foreground))]' : 'text-[hsl(var(--muted-foreground))]'
        )}
      >
        {label}
      </span>
    </div>
  )
}

// ─── Утилиты ─────────────────────────────────────────────────

interface ParseResult {
  accounts: Account[]
  totalInFile: number   // сколько строк логин:пароль в файле
  skippedDuplicates: number // сколько пропущено (уже есть в базе)
}

function parseTxtAccounts(content: string, existing: Account[]): ParseResult {
  const existingLogins = new Set(existing.map((a) => a.login.toLowerCase()))
  const seen = new Set<string>()
  const accounts: Account[] = []
  let totalInFile = 0
  let skippedDuplicates = 0

  const lines = content.split(/\r?\n/)
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#') || trimmed.startsWith('//')) continue

    // Формат: login:password
    const colonIdx = trimmed.indexOf(':')
    if (colonIdx === -1) continue

    const login = trimmed.slice(0, colonIdx).trim()
    const password = trimmed.slice(colonIdx + 1).trim()

    if (!login || !password) continue
    totalInFile++

    // Пропускаем дубликаты внутри файла
    if (seen.has(login.toLowerCase())) continue
    seen.add(login.toLowerCase())

    // Пропускаем аккаунты, которые уже есть
    if (existingLogins.has(login.toLowerCase())) {
      skippedDuplicates++
      continue
    }

    accounts.push({
      id: generateId(),
      login,
      password,
      maFile: false,
      addedAt: new Date().toISOString(),
      status: 'waiting',
      isFarmed: false,
      isDropCollected: false,
    })
  }

  return { accounts, totalInFile, skippedDuplicates }
}

function pluralAccounts(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'аккаунт'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'аккаунта'
  return 'аккаунтов'
}
