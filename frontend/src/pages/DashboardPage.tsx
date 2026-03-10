import { useEffect, useState } from 'react'
import api from '@/lib/api'

export function DashboardPage() {
  const [backendStatus, setBackendStatus] = useState<string>('Проверка...')

  useEffect(() => {
    api.get('/api/health')
      .then((res) => setBackendStatus(`OK — ${res.data.app} v${res.data.version}`))
      .catch(() => setBackendStatus('Недоступен'))
  }, [])

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Главная</h1>
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
        <div className="text-sm text-[hsl(var(--muted-foreground))]">Статус backend</div>
        <div className="text-lg font-semibold mt-1">{backendStatus}</div>
      </div>
    </div>
  )
}
