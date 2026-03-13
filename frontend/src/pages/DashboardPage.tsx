import { useEffect, useState } from 'react'
import api from '@/lib/api'
import { Users, Globe, FolderOpen, Shield } from 'lucide-react'

export function DashboardPage() {
  const [backendStatus, setBackendStatus] = useState<string>('Проверка...')
  const [accounts, setAccounts] = useState(0)
  const [proxies, setProxies] = useState(0)
  const [groups, setGroups] = useState(0)

  useEffect(() => {
    api.get('/api/health')
      .then((res) => setBackendStatus(`OK — ${res.data.app} v${res.data.version}`))
      .catch(() => setBackendStatus('Недоступен'))

    api.get('/api/accounts/count').then(r => setAccounts(r.data.count)).catch(() => {})
    api.get('/api/proxies/count').then(r => setProxies(r.data.count)).catch(() => {})
    api.get('/api/groups/').then(r => setGroups(r.data.length)).catch(() => {})
  }, [])

  const cards = [
    { icon: Users, label: 'Аккаунтов', value: accounts, color: 'text-blue-400' },
    { icon: Globe, label: 'Прокси', value: proxies, color: 'text-green-400' },
    { icon: FolderOpen, label: 'Групп', value: groups, color: 'text-purple-400' },
  ]

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Главная</h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {cards.map(c => (
          <div key={c.label} className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
            <div className="flex items-center gap-3">
              <c.icon size={20} className={c.color} />
              <span className="text-sm text-[hsl(var(--muted-foreground))]">{c.label}</span>
            </div>
            <div className="text-3xl font-bold mt-2">{c.value}</div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <div className="text-sm text-[hsl(var(--muted-foreground))]">Статус backend</div>
        <div className="text-lg font-semibold mt-1">{backendStatus}</div>
      </div>
    </div>
  )
}
