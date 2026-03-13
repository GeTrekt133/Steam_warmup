import { useState, useEffect, useRef } from 'react'
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
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Типы ────────────────────────────────────────────────────

interface Account {
  id: string
  login: string
  password: string
  maFile: boolean        // есть ли привязанный maFile
  maFileName?: string    // имя файла maFile
  addedAt: string        // дата добавления (ISO)
  steamId?: string       // Steam ID аккаунта
  rank?: number          // ранг аккаунта
  exp?: number           // опыт аккаунта
  status: string         // текущий статус аккаунта (wait, farming, warmup, drop и тд)
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

  function handleOpenInBrowser(account: Account) {
    const ids = getTargetIds(account)
    const targets = accounts.filter((a) => ids.has(a.id))
    for (const acc of targets) {
      window.open(`https://steamcommunity.com/id/${acc.login}`, '_blank')
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
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDeleteSelected}
            >
              <Trash2 className="h-4 w-4" />
              Удалить выбранные ({selectedIds.size})
            </Button>
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
              <TableHead className="w-20">Ранг</TableHead>
              <TableHead className="w-20">EXP</TableHead>
              <TableHead className="w-32">maFile</TableHead>
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
                <TableCell className="text-sm text-[hsl(var(--muted-foreground))]">
                  {account.status}
                </TableCell>
                <TableCell className="text-xs text-[hsl(var(--muted-foreground))] font-mono">
                  {account.steamId || '—'}
                </TableCell>
                <TableCell className="text-center text-sm">
                  {account.rank ?? '—'}
                </TableCell>
                <TableCell className="text-center text-sm">
                  {account.exp ?? '—'}
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
                <TableCell colSpan={12} className="text-center py-8 text-[hsl(var(--muted-foreground))]">
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
          onCollectDrop={handleCollectDrop}
          onToggleFarmed={handleToggleFarmed}
          onToggleDropCollected={handleToggleDropCollected}
          onDelete={handleDeleteFromMenu}
        />
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
  onCollectDrop,
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
  onCollectDrop: (acc: Account) => void
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
      onClick: () => copyToClipboard(allTargets.filter((a) => a.maFile).map((a) => a.login).join('\n'), '2fa'),
      disabled: !allTargets.some((a) => a.maFile),
    },
    { type: 'separator' },
    {
      label: 'Открыть в браузере',
      icon: Globe,
      onClick: () => onOpenBrowser(account),
    },
    {
      label: 'Собрать дроп',
      icon: Package,
      onClick: () => onCollectDrop(account),
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

  const txtInputRef = useRef<HTMLInputElement>(null)
  const maInputRef = useRef<HTMLInputElement>(null)

  // ─── Шаг 1: Импорт TXT (через <input type="file">) ─────
  function handleTxtClick() {
    txtInputRef.current?.click()
  }

  function handleTxtFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setTxtError('')

    const reader = new FileReader()
    reader.onload = (ev) => {
      const content = ev.target?.result as string
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
    reader.onerror = () => {
      setTxtError('Ошибка чтения файла')
    }
    reader.readAsText(file, 'utf-8')

    // Сбрасываем input чтобы можно было выбрать тот же файл повторно
    e.target.value = ''
  }

  // ─── Шаг 2: Импорт maFiles (через <input type="file" multiple>) ─
  function handleMaClick() {
    maInputRef.current?.click()
  }

  function handleMaFilesChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return

    let matched = 0
    let processed = 0
    const total = files.length
    const updatedAccounts = [...parsedAccounts]

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const reader = new FileReader()
      reader.onload = (ev) => {
        processed++
        try {
          const content = ev.target?.result as string
          const json = JSON.parse(content)
          const accountName: string | undefined = json.account_name

          if (accountName) {
            const account = updatedAccounts.find(
              (a) => a.login.toLowerCase() === accountName.toLowerCase() && !a.maFile
            )
            if (account) {
              account.maFile = true
              account.maFileName = accountName + '.maFile'
              matched++
            }
          }
        } catch {
          // Пропускаем битые maFile
        }

        // Когда все файлы обработаны
        if (processed === total) {
          setParsedAccounts([...updatedAccounts])
          setMaResult({ matched, total })
          setStep('done')
        }
      }
      reader.readAsText(file, 'utf-8')
    }

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
      {/* Скрытые файловые инпуты */}
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
                  <Button variant="ghost" onClick={handleSkipMaFiles}>
                    Пропустить
                  </Button>
                </div>
              </div>
            </div>
          </div>
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
