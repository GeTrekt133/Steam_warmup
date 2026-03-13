import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'
import {
  Globe, Plus, Upload, Trash2, RefreshCw, Zap,
  Search, X, ChevronLeft, ChevronRight, Check, XCircle,
} from 'lucide-react'

interface Proxy {
  id: number
  host: string
  port: number
  protocol: string
  username: string | null
  is_alive: boolean
  ping_ms: number | null
  last_checked_at: string | null
  country: string | null
  created_at: string
}

type Modal = null | 'create' | 'import-txt'

export function ProxiesPage() {
  const [proxies, setProxies] = useState<Proxy[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [modal, setModal] = useState<Modal>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)

  // Form
  const [formHost, setFormHost] = useState('')
  const [formPort, setFormPort] = useState('')
  const [formProtocol, setFormProtocol] = useState('http')
  const [formUser, setFormUser] = useState('')
  const [formPass, setFormPass] = useState('')
  const [importTxt, setImportTxt] = useState('')
  const [message, setMessage] = useState<{ text: string; type: 'ok' | 'err' } | null>(null)

  const LIMIT = 100

  const loadProxies = useCallback(async () => {
    try {
      const [list, cnt] = await Promise.all([
        api.get('/api/proxies/', { params: { skip: page * LIMIT, limit: LIMIT } }),
        api.get('/api/proxies/count'),
      ])
      setProxies(list.data)
      setTotal(cnt.data.count)
    } catch { /* ignore */ }
  }, [page])

  useEffect(() => { loadProxies() }, [loadProxies])

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMessage({ text, type })
    setTimeout(() => setMessage(null), 3000)
  }

  const handleCreate = async () => {
    if (!formHost || !formPort) return
    setLoading(true)
    try {
      await api.post('/api/proxies/', {
        host: formHost, port: parseInt(formPort), protocol: formProtocol,
        username: formUser || undefined, password: formPass || undefined,
      })
      flash('Прокси добавлен')
      setModal(null); setFormHost(''); setFormPort(''); setFormUser(''); setFormPass('')
      loadProxies()
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка', 'err')
    } finally { setLoading(false) }
  }

  const handleImportTxt = async () => {
    if (!importTxt.trim()) return
    setLoading(true)
    try {
      const r = await api.post('/api/proxies/import/txt', { content: importTxt })
      flash(`Импортировано: ${r.data.imported}, пропущено: ${r.data.skipped}`)
      setModal(null); setImportTxt('')
      loadProxies()
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка импорта', 'err')
    } finally { setLoading(false) }
  }

  const handleCheckAll = async () => {
    setChecking(true)
    try {
      const r = await api.post('/api/proxies/check-all')
      const alive = r.data.filter((p: any) => p.is_alive).length
      flash(`Проверено: ${r.data.length}, живых: ${alive}`)
      loadProxies()
    } catch (e: any) {
      flash(e.response?.data?.detail || 'Ошибка проверки', 'err')
    } finally { setChecking(false) }
  }

  const handleCheckSelected = async () => {
    if (!selected.size) return
    setChecking(true)
    try {
      const r = await api.post('/api/proxies/check', [...selected])
      const alive = r.data.filter((p: any) => p.is_alive).length
      flash(`Проверено: ${r.data.length}, живых: ${alive}`)
      loadProxies()
    } catch { flash('Ошибка проверки', 'err') }
    finally { setChecking(false) }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить прокси?')) return
    try {
      await api.delete(`/api/proxies/${id}`)
      flash('Удалён')
      loadProxies()
    } catch { flash('Ошибка', 'err') }
  }

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === proxies.length) setSelected(new Set())
    else setSelected(new Set(proxies.map(p => p.id)))
  }

  const totalPages = Math.ceil(total / LIMIT)

  return (
    <div className="p-6 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Globe size={24} />
          <h1 className="text-2xl font-bold">Прокси</h1>
          <span className="text-sm text-[hsl(var(--muted-foreground))]">({total})</span>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setModal('create')} className="btn-primary">
            <Plus size={16} /> Добавить
          </button>
          <button onClick={() => setModal('import-txt')} className="btn-secondary">
            <Upload size={16} /> Импорт TXT
          </button>
          <button onClick={selected.size > 0 ? handleCheckSelected : handleCheckAll} disabled={checking} className="btn-secondary">
            <RefreshCw size={16} className={checking ? 'animate-spin' : ''} />
            {checking ? 'Проверка...' : selected.size > 0 ? `Проверить (${selected.size})` : 'Проверить все'}
          </button>
        </div>
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
                <input type="checkbox" checked={selected.size === proxies.length && proxies.length > 0} onChange={toggleAll} />
              </th>
              <th className="th">Хост</th>
              <th className="th">Порт</th>
              <th className="th">Протокол</th>
              <th className="th">Авторизация</th>
              <th className="th text-center">Статус</th>
              <th className="th text-center">Пинг</th>
              <th className="th">Проверен</th>
              <th className="th w-20">Действия</th>
            </tr>
          </thead>
          <tbody>
            {proxies.map(px => (
              <tr key={px.id} className={`border-t border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))] ${selected.has(px.id) ? 'bg-[hsl(var(--accent))]' : ''}`}>
                <td className="td">
                  <input type="checkbox" checked={selected.has(px.id)} onChange={() => toggleSelect(px.id)} />
                </td>
                <td className="td font-mono">{px.host}</td>
                <td className="td font-mono">{px.port}</td>
                <td className="td">
                  <span className="px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-400">{px.protocol}</span>
                </td>
                <td className="td text-xs text-[hsl(var(--muted-foreground))]">{px.username || '—'}</td>
                <td className="td text-center">
                  {px.last_checked_at ? (
                    px.is_alive ? <Check size={16} className="inline text-green-400" /> : <XCircle size={16} className="inline text-red-400" />
                  ) : (
                    <span className="text-[hsl(var(--muted-foreground))]">—</span>
                  )}
                </td>
                <td className="td text-center font-mono text-xs">
                  {px.ping_ms != null ? `${px.ping_ms}ms` : '—'}
                </td>
                <td className="td text-xs text-[hsl(var(--muted-foreground))]">
                  {px.last_checked_at ? new Date(px.last_checked_at).toLocaleTimeString() : '—'}
                </td>
                <td className="td">
                  <button onClick={() => handleDelete(px.id)} title="Удалить" className="icon-btn text-red-400 hover:text-red-300">
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
            {proxies.length === 0 && (
              <tr>
                <td colSpan={9} className="td text-center text-[hsl(var(--muted-foreground))] py-12">
                  Нет прокси. Нажмите «Добавить» или импортируйте из TXT.
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

      {modal === 'create' && (
        <ModalOverlay onClose={() => setModal(null)} title="Новый прокси">
          <div className="flex gap-2 mb-3">
            <input className="input flex-1" placeholder="Хост (IP)" value={formHost} onChange={e => setFormHost(e.target.value)} />
            <input className="input w-24" placeholder="Порт" type="number" value={formPort} onChange={e => setFormPort(e.target.value)} />
          </div>
          <select className="input w-full mb-3" value={formProtocol} onChange={e => setFormProtocol(e.target.value)}>
            <option value="http">HTTP</option>
            <option value="socks5">SOCKS5</option>
          </select>
          <input className="input w-full mb-3" placeholder="Логин (опц.)" value={formUser} onChange={e => setFormUser(e.target.value)} />
          <input className="input w-full mb-4" placeholder="Пароль (опц.)" type="password" value={formPass} onChange={e => setFormPass(e.target.value)} />
          <button onClick={handleCreate} disabled={loading || !formHost || !formPort} className="btn-primary w-full">
            {loading ? 'Создание...' : 'Добавить'}
          </button>
        </ModalOverlay>
      )}

      {modal === 'import-txt' && (
        <ModalOverlay onClose={() => setModal(null)} title="Импорт прокси из TXT">
          <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">
            Форматы: host:port, host:port:user:pass, protocol://host:port, protocol://user:pass@host:port
          </p>
          <textarea
            className="input w-full h-48 mb-4 font-mono text-xs resize-none"
            placeholder={"1.2.3.4:8080\nsocks5://5.6.7.8:1080\n9.10.11.12:3128:user:pass"}
            value={importTxt}
            onChange={e => setImportTxt(e.target.value)}
          />
          <button onClick={handleImportTxt} disabled={loading || !importTxt.trim()} className="btn-primary w-full">
            {loading ? 'Импорт...' : `Импортировать (${importTxt.trim().split('\n').filter(l => l.trim()).length} строк)`}
          </button>
        </ModalOverlay>
      )}
    </div>
  )
}

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
