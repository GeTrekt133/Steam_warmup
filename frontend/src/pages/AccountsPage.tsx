import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'
import {
  Users, Plus, Upload, FileText, Trash2, Globe, Shield,
  Search, ChevronLeft, ChevronRight, X, Copy, Check,
} from 'lucide-react'

interface Account {
  id: number
  login: string
  steam_id: string | null
  status: string
  steam_level: number
  cs2_hours: number
  balance: number
  is_limited: boolean
  has_mafile: boolean
  proxy_id: number | null
  group_id: number | null
  note: string | null
  created_at: string
}

interface Group {
  id: number
  name: string
  color: string
  account_count: number
}

type Modal = null | 'create' | 'import-txt' | 'import-mafile' | 'guard'

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500/20 text-green-400',
  banned: 'bg-red-500/20 text-red-400',
  limited: 'bg-yellow-500/20 text-yellow-400',
  cooldown: 'bg-blue-500/20 text-blue-400',
  unchecked: 'bg-gray-500/20 text-gray-400',
  error: 'bg-red-500/20 text-red-400',
}

export function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [groupFilter, setGroupFilter] = useState<string>('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [modal, setModal] = useState<Modal>(null)
  const [loading, setLoading] = useState(false)

  // Modal state
  const [formLogin, setFormLogin] = useState('')
  const [formPassword, setFormPassword] = useState('')
  const [formNote, setFormNote] = useState('')
  const [importTxt, setImportTxt] = useState('')
  const [importMafile, setImportMafile] = useState('')
  const [importPassword, setImportPassword] = useState('')
  const [guardCode, setGuardCode] = useState('')
  const [guardTtl, setGuardTtl] = useState(0)
  const [guardAccountId, setGuardAccountId] = useState(0)
  const [message, setMessage] = useState<{ text: string; type: 'ok' | 'err' } | null>(null)

  const LIMIT = 50

  const loadAccounts = useCallback(async () => {
    try {
      const params: Record<string, string | number> = { skip: page * LIMIT, limit: LIMIT }
      if (search) params.search = search
      if (groupFilter) params.group_id = groupFilter
      const [accs, cnt] = await Promise.all([
        api.get('/api/accounts/', { params }),
        api.get('/api/accounts/count'),
      ])
      setAccounts(accs.data)
      setTotal(cnt.data.count)
    } catch { /* ignore */ }
  }, [page, search, groupFilter])

  const loadGroups = useCallback(async () => {
    try {
      const r = await api.get('/api/groups/')
      setGroups(r.data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadAccounts() }, [loadAccounts])
  useEffect(() => { loadGroups() }, [loadGroups])

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMessage({ text, type })
    setTimeout(() => setMessage(null), 3000)
  }

  // ── Actions ──

  const handleCreate = async () => {
    if (!formLogin) return
    setLoading(true)
    try {
      await api.post('/api/accounts/', { login: formLogin, password: formPassword, note: formNote || undefined })
      flash('Аккаунт создан')
      setModal(null); setFormLogin(''); setFormPassword(''); setFormNote('')
      loadAccounts()
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка', 'err')
    } finally { setLoading(false) }
  }

  const handleImportTxt = async () => {
    if (!importTxt.trim()) return
    setLoading(true)
    try {
      const r = await api.post('/api/accounts/import/txt', { content: importTxt })
      flash(`Импортировано: ${r.data.imported}, пропущено: ${r.data.skipped}`)
      setModal(null); setImportTxt('')
      loadAccounts()
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка импорта', 'err')
    } finally { setLoading(false) }
  }

  const handleImportMafile = async () => {
    if (!importMafile.trim()) return
    setLoading(true)
    try {
      const mafileJson = JSON.parse(importMafile)
      await api.post('/api/accounts/import/mafile', {
        mafile_json: mafileJson,
        password: importPassword || undefined,
      })
      flash('maFile импортирован')
      setModal(null); setImportMafile(''); setImportPassword('')
      loadAccounts()
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Невалидный JSON', 'err')
    } finally { setLoading(false) }
  }

  const handleDelete = async (ids: number[]) => {
    if (!ids.length) return
    if (!confirm(`Удалить ${ids.length} аккаунт(ов)?`)) return
    try {
      await api.post('/api/accounts/delete-bulk', ids)
      flash(`Удалено: ${ids.length}`)
      setSelected(new Set())
      loadAccounts()
    } catch { flash('Ошибка удаления', 'err') }
  }

  const handleOpenBrowser = async (id: number) => {
    try {
      const r = await api.post(`/api/accounts/${id}/open-browser`)
      flash(r.data.message)
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка', 'err')
    }
  }

  const handleGuardCode = async (id: number) => {
    try {
      const r = await api.get(`/api/accounts/${id}/guard-code`)
      setGuardCode(r.data.code)
      setGuardTtl(r.data.ttl)
      setGuardAccountId(id)
      setModal('guard')
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Нет maFile', 'err')
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    flash('Скопировано')
  }

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === accounts.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(accounts.map(a => a.id)))
    }
  }

  const totalPages = Math.ceil(total / LIMIT)

  return (
    <div className="p-6 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Users size={24} />
          <h1 className="text-2xl font-bold">Аккаунты</h1>
          <span className="text-sm text-[hsl(var(--muted-foreground))]">({total})</span>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setModal('create')} className="btn-primary">
            <Plus size={16} /> Добавить
          </button>
          <button onClick={() => setModal('import-txt')} className="btn-secondary">
            <Upload size={16} /> TXT
          </button>
          <button onClick={() => setModal('import-mafile')} className="btn-secondary">
            <FileText size={16} /> maFile
          </button>
          {selected.size > 0 && (
            <button onClick={() => handleDelete([...selected])} className="btn-danger">
              <Trash2 size={16} /> Удалить ({selected.size})
            </button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <input
            type="text"
            placeholder="Поиск по логину..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0) }}
            className="input pl-9 w-full"
          />
        </div>
        <select
          value={groupFilter}
          onChange={e => { setGroupFilter(e.target.value); setPage(0) }}
          className="input w-48"
        >
          <option value="">Все группы</option>
          {groups.map(g => (
            <option key={g.id} value={g.id}>{g.name} ({g.account_count})</option>
          ))}
        </select>
      </div>

      {/* Message */}
      {message && (
        <div className={`mb-3 px-4 py-2 rounded text-sm ${message.type === 'ok' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
          {message.text}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto rounded-lg border border-[hsl(var(--border))]">
        <table className="w-full text-sm">
          <thead className="bg-[hsl(var(--secondary))] sticky top-0">
            <tr>
              <th className="th w-10">
                <input type="checkbox" checked={selected.size === accounts.length && accounts.length > 0} onChange={toggleAll} />
              </th>
              <th className="th">Логин</th>
              <th className="th">Steam ID</th>
              <th className="th">Статус</th>
              <th className="th text-center">Уровень</th>
              <th className="th text-center">CS2</th>
              <th className="th text-center">Баланс</th>
              <th className="th text-center">maFile</th>
              <th className="th">Заметка</th>
              <th className="th w-32">Действия</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map(acc => (
              <tr key={acc.id} className={`border-t border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))] ${selected.has(acc.id) ? 'bg-[hsl(var(--accent))]' : ''}`}>
                <td className="td">
                  <input type="checkbox" checked={selected.has(acc.id)} onChange={() => toggleSelect(acc.id)} />
                </td>
                <td className="td font-medium">{acc.login}</td>
                <td className="td text-xs text-[hsl(var(--muted-foreground))]">{acc.steam_id || '—'}</td>
                <td className="td">
                  <span className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[acc.status] || ''}`}>
                    {acc.status}
                  </span>
                </td>
                <td className="td text-center">{acc.steam_level}</td>
                <td className="td text-center">{acc.cs2_hours}h</td>
                <td className="td text-center">${acc.balance.toFixed(2)}</td>
                <td className="td text-center">{acc.has_mafile ? '2FA' : '—'}</td>
                <td className="td text-xs text-[hsl(var(--muted-foreground))] max-w-[150px] truncate">{acc.note || ''}</td>
                <td className="td">
                  <div className="flex gap-1">
                    <button onClick={() => handleOpenBrowser(acc.id)} title="Открыть в браузере" className="icon-btn">
                      <Globe size={14} />
                    </button>
                    {acc.has_mafile && (
                      <button onClick={() => handleGuardCode(acc.id)} title="Steam Guard код" className="icon-btn">
                        <Shield size={14} />
                      </button>
                    )}
                    <button onClick={() => handleDelete([acc.id])} title="Удалить" className="icon-btn text-red-400 hover:text-red-300">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {accounts.length === 0 && (
              <tr>
                <td colSpan={10} className="td text-center text-[hsl(var(--muted-foreground))] py-12">
                  Нет аккаунтов. Нажмите «Добавить» или импортируйте из TXT / maFile.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-sm text-[hsl(var(--muted-foreground))]">
          <span>Стр. {page + 1} из {totalPages}</span>
          <div className="flex gap-2">
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)} className="icon-btn"><ChevronLeft size={16} /></button>
            <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)} className="icon-btn"><ChevronRight size={16} /></button>
          </div>
        </div>
      )}

      {/* ── Modals ── */}

      {/* Create */}
      {modal === 'create' && (
        <ModalOverlay onClose={() => setModal(null)} title="Новый аккаунт">
          <input className="input w-full mb-3" placeholder="Логин Steam" value={formLogin} onChange={e => setFormLogin(e.target.value)} />
          <input className="input w-full mb-3" placeholder="Пароль" type="password" value={formPassword} onChange={e => setFormPassword(e.target.value)} />
          <input className="input w-full mb-4" placeholder="Заметка (опц.)" value={formNote} onChange={e => setFormNote(e.target.value)} />
          <button onClick={handleCreate} disabled={loading || !formLogin} className="btn-primary w-full">
            {loading ? 'Создание...' : 'Создать'}
          </button>
        </ModalOverlay>
      )}

      {/* Import TXT */}
      {modal === 'import-txt' && (
        <ModalOverlay onClose={() => setModal(null)} title="Импорт из TXT">
          <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">Формат: login:password (каждый с новой строки)</p>
          <textarea
            className="input w-full h-48 mb-4 font-mono text-xs resize-none"
            placeholder={"user1:pass1\nuser2:pass2\nuser3:pass3"}
            value={importTxt}
            onChange={e => setImportTxt(e.target.value)}
          />
          <button onClick={handleImportTxt} disabled={loading || !importTxt.trim()} className="btn-primary w-full">
            {loading ? 'Импорт...' : `Импортировать (${importTxt.trim().split('\n').filter(l => l.includes(':')).length} строк)`}
          </button>
        </ModalOverlay>
      )}

      {/* Import maFile */}
      {modal === 'import-mafile' && (
        <ModalOverlay onClose={() => setModal(null)} title="Импорт maFile">
          <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">Вставьте JSON из maFile (SteamDesktopAuthenticator)</p>
          <textarea
            className="input w-full h-40 mb-3 font-mono text-xs resize-none"
            placeholder='{"account_name":"...","shared_secret":"..."}'
            value={importMafile}
            onChange={e => setImportMafile(e.target.value)}
          />
          <input className="input w-full mb-4" placeholder="Пароль аккаунта (опц.)" type="password" value={importPassword} onChange={e => setImportPassword(e.target.value)} />
          <button onClick={handleImportMafile} disabled={loading || !importMafile.trim()} className="btn-primary w-full">
            {loading ? 'Импорт...' : 'Импортировать maFile'}
          </button>
        </ModalOverlay>
      )}

      {/* Guard Code */}
      {modal === 'guard' && (
        <ModalOverlay onClose={() => setModal(null)} title="Steam Guard код">
          <div className="text-center">
            <div className="text-4xl font-mono font-bold tracking-[0.3em] mb-2">{guardCode}</div>
            <div className="text-sm text-[hsl(var(--muted-foreground))] mb-4">Истекает через {guardTtl}с</div>
            <div className="flex gap-2 justify-center">
              <button onClick={() => copyToClipboard(guardCode)} className="btn-secondary">
                <Copy size={14} /> Копировать
              </button>
              <button onClick={() => handleGuardCode(guardAccountId)} className="btn-secondary">
                Обновить
              </button>
            </div>
          </div>
        </ModalOverlay>
      )}
    </div>
  )
}

// ── Modal wrapper ──

function ModalOverlay({ children, title, onClose }: { children: React.ReactNode; title: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-lg p-6 w-full max-w-md shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="icon-btn"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}
