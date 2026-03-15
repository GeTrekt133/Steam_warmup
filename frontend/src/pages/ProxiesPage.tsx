import { useEffect, useState, useCallback } from 'react'
import {
  Globe, Plus, Upload, Trash2, RefreshCw,
  X, ChevronLeft, ChevronRight, Check, XCircle,
} from 'lucide-react'

interface Proxy {
  id: number
  host: string
  port: number
  protocol: string
  username: string | null
  password: string | null
  is_alive: boolean | null
  ping_ms: number | null
  last_checked_at: string | null
  created_at: string
}

type Modal = null | 'create' | 'import-txt'

const STORAGE_KEY = 'panel_proxies'
const LIMIT = 100

function loadFromStorage(): Proxy[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveToStorage(proxies: Proxy[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(proxies))
}

let nextId = Date.now()
function genId(): number {
  return nextId++
}

/** Парсинг строки прокси в объект. Поддерживаемые форматы:
 *  - host:port
 *  - host:port:user:pass
 *  - protocol://host:port
 *  - protocol://user:pass@host:port
 */
function parseProxyLine(line: string): Proxy | null {
  line = line.trim()
  if (!line || line.startsWith('#')) return null

  let protocol = 'http'
  let host = ''
  let port = 0
  let username: string | null = null
  let password: string | null = null

  // protocol://...
  const protoMatch = line.match(/^(https?|socks[45]?):\/\/(.+)$/i)
  if (protoMatch) {
    protocol = protoMatch[1].toLowerCase()
    line = protoMatch[2]
  }

  // user:pass@host:port
  const atIdx = line.lastIndexOf('@')
  if (atIdx !== -1) {
    const auth = line.slice(0, atIdx)
    const rest = line.slice(atIdx + 1)
    const authParts = auth.split(':')
    username = authParts[0] || null
    password = authParts.slice(1).join(':') || null
    const [h, p] = rest.split(':')
    host = h
    port = parseInt(p)
  } else {
    // host:port or host:port:user:pass
    const parts = line.split(':')
    if (parts.length >= 2) {
      host = parts[0]
      port = parseInt(parts[1])
      if (parts.length >= 4) {
        username = parts[2] || null
        password = parts[3] || null
      }
    }
  }

  if (!host || !port || isNaN(port)) return null

  return {
    id: genId(),
    host,
    port,
    protocol,
    username,
    password,
    is_alive: null,
    ping_ms: null,
    last_checked_at: null,
    created_at: new Date().toISOString(),
  }
}

/** Проверка прокси — пытаемся подключиться через fetch с таймаутом */
async function checkProxy(px: Proxy): Promise<{ alive: boolean; ping: number | null }> {
  const start = performance.now()
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10000)
    const url = `${px.protocol}://${px.host}:${px.port}`
    await fetch(url, { signal: controller.signal, mode: 'no-cors' })
    clearTimeout(timeout)
    const ping = Math.round(performance.now() - start)
    return { alive: true, ping }
  } catch {
    return { alive: false, ping: null }
  }
}

export function ProxiesPage() {
  const [allProxies, setAllProxies] = useState<Proxy[]>([])
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

  // Загрузка из localStorage при монтировании
  useEffect(() => {
    const stored = loadFromStorage()
    setAllProxies(stored)
    // Инициализируем nextId чтобы не было коллизий
    if (stored.length > 0) {
      nextId = Math.max(...stored.map(p => p.id)) + 1
    }
  }, [])

  // Сохранение в localStorage при каждом изменении
  const saveAndSet = useCallback((proxies: Proxy[]) => {
    setAllProxies(proxies)
    saveToStorage(proxies)
  }, [])

  const total = allProxies.length
  const totalPages = Math.ceil(total / LIMIT)
  const proxies = allProxies.slice(page * LIMIT, (page + 1) * LIMIT)

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMessage({ text, type })
    setTimeout(() => setMessage(null), 3000)
  }

  const handleCreate = () => {
    if (!formHost || !formPort) return
    const px: Proxy = {
      id: genId(),
      host: formHost,
      port: parseInt(formPort),
      protocol: formProtocol,
      username: formUser || null,
      password: formPass || null,
      is_alive: null,
      ping_ms: null,
      last_checked_at: null,
      created_at: new Date().toISOString(),
    }
    saveAndSet([...allProxies, px])
    flash('Прокси добавлен')
    setModal(null)
    setFormHost(''); setFormPort(''); setFormUser(''); setFormPass('')
  }

  const handleImportTxt = () => {
    if (!importTxt.trim()) return
    setLoading(true)
    const lines = importTxt.split('\n')
    let imported = 0
    let skipped = 0
    const newProxies = [...allProxies]

    for (const line of lines) {
      const px = parseProxyLine(line)
      if (px) {
        newProxies.push(px)
        imported++
      } else if (line.trim()) {
        skipped++
      }
    }

    saveAndSet(newProxies)
    flash(`Импортировано: ${imported}, пропущено: ${skipped}`)
    setModal(null)
    setImportTxt('')
    setLoading(false)
  }

  const handleCheckAll = async () => {
    setChecking(true)
    const updated = [...allProxies]
    let alive = 0
    for (let i = 0; i < updated.length; i++) {
      const result = await checkProxy(updated[i])
      updated[i] = {
        ...updated[i],
        is_alive: result.alive,
        ping_ms: result.ping,
        last_checked_at: new Date().toISOString(),
      }
      if (result.alive) alive++
      // Обновляем UI каждые 5 проверок
      if (i % 5 === 0) {
        saveAndSet([...updated])
      }
    }
    saveAndSet(updated)
    flash(`Проверено: ${updated.length}, живых: ${alive}`)
    setChecking(false)
  }

  const handleCheckSelected = async () => {
    if (!selected.size) return
    setChecking(true)
    const updated = [...allProxies]
    let alive = 0
    let checked = 0
    for (let i = 0; i < updated.length; i++) {
      if (!selected.has(updated[i].id)) continue
      const result = await checkProxy(updated[i])
      updated[i] = {
        ...updated[i],
        is_alive: result.alive,
        ping_ms: result.ping,
        last_checked_at: new Date().toISOString(),
      }
      if (result.alive) alive++
      checked++
      if (checked % 5 === 0) {
        saveAndSet([...updated])
      }
    }
    saveAndSet(updated)
    flash(`Проверено: ${checked}, живых: ${alive}`)
    setChecking(false)
  }

  const handleDelete = (id: number) => {
    saveAndSet(allProxies.filter(p => p.id !== id))
    flash('Удалён')
  }

  const handleDeleteSelected = () => {
    if (!selected.size) return
    if (!confirm(`Удалить ${selected.size} прокси?`)) return
    saveAndSet(allProxies.filter(p => !selected.has(p.id)))
    setSelected(new Set())
    flash(`Удалено: ${selected.size}`)
  }

  const handleDeleteAll = () => {
    if (!total) return
    if (!confirm(`Удалить ВСЕ ${total} прокси?`)) return
    saveAndSet([])
    setSelected(new Set())
    flash(`Удалено: ${total}`)
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
          <button
            onClick={selected.size > 0 ? handleDeleteSelected : handleDeleteAll}
            disabled={loading || total === 0}
            className="btn-secondary text-red-400 hover:text-red-300 hover:border-red-500/50"
          >
            <Trash2 size={16} />
            {selected.size > 0 ? `Удалить (${selected.size})` : 'Удалить все'}
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
                  {px.is_alive === true && <Check size={16} className="inline text-green-400" />}
                  {px.is_alive === false && <XCircle size={16} className="inline text-red-400" />}
                  {px.is_alive === null && <span className="text-[hsl(var(--muted-foreground))]">—</span>}
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
          <button onClick={handleCreate} disabled={!formHost || !formPort} className="btn-primary w-full">
            Добавить
          </button>
        </ModalOverlay>
      )}

      {modal === 'import-txt' && (
        <ModalOverlay onClose={() => setModal(null)} title="Импорт прокси из TXT">
          <p className="text-xs text-[hsl(var(--muted-foreground))] mb-2">
            Форматы: host:port, host:port:user:pass, protocol://host:port, protocol://user:pass@host:port
          </p>

          {/* Кнопка выбора файла */}
          <label className="flex items-center justify-center gap-2 w-full px-4 py-3 mb-3 border-2 border-dashed border-[hsl(var(--border))] rounded-lg cursor-pointer hover:border-[hsl(var(--primary))] hover:bg-[hsl(var(--accent))] transition-colors">
            <Upload size={18} className="text-[hsl(var(--muted-foreground))]" />
            <span className="text-sm text-[hsl(var(--muted-foreground))]">Выбрать файл .txt</span>
            <input
              type="file"
              accept=".txt"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                const reader = new FileReader()
                reader.onload = () => {
                  setImportTxt(reader.result as string)
                }
                reader.readAsText(file, 'utf-8')
                e.target.value = ''
              }}
            />
          </label>

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
