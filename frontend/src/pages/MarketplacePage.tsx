import { useState, useEffect } from 'react'
import api from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/Table'
import {
  Wallet,
  ShoppingCart,
  Key,
  CheckCircle,
  AlertCircle,
  ExternalLink,
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Типы ────────────────────────────────────────────────────

interface Provider {
  id: string
  name: string
  description: string
  payment_methods: string[]
  regions: string[]
  automation: string
  status: string
  url: string
  configured: boolean
  price_examples: { denomination: string; approx_cost: string; region: string }[]
}

interface HistoryEntry {
  provider: string
  code: string | null
  amount: string
  cost: number
  cost_currency: string
  success: boolean
  error: string | null
  redeemed_to: string[]
  timestamp: number
}

interface LocalAccount {
  id: string
  login: string
}

// ─── Компонент ───────────────────────────────────────────────

export function MarketplacePage() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [selectedProvider, setSelectedProvider] = useState<string>('g2a')
  const [history, setHistory] = useState<HistoryEntry[]>([])

  // Покупка
  const [buyQuery, setBuyQuery] = useState('Steam Wallet $5 USD')
  const [buyLoading, setBuyLoading] = useState(false)
  const [buyResult, setBuyResult] = useState<{ success: boolean; code?: string; error?: string } | null>(null)

  // Ручной redeem
  const [redeemCode, setRedeemCode] = useState('')
  const [redeemBot, setRedeemBot] = useState('')
  const [redeemLoading, setRedeemLoading] = useState(false)
  const [redeemResult, setRedeemResult] = useState<{ success: boolean; message: string } | null>(null)

  // Аккаунты
  const [accounts, setAccounts] = useState<LocalAccount[]>([])

  // ─── Загрузка ─────────────────────────────────────────────

  useEffect(() => {
    api.get('/api/topup/providers').then((r) => setProviders(r.data.providers ?? [])).catch(() => {})
    api.get('/api/topup/history').then((r) => setHistory(r.data.history ?? [])).catch(() => {})
    try {
      const raw = localStorage.getItem('steam_accounts')
      setAccounts(raw ? JSON.parse(raw) : [])
    } catch { setAccounts([]) }
  }, [])

  const currentProvider = providers.find((p) => p.id === selectedProvider)

  // ─── Покупка ──────────────────────────────────────────────

  async function handleBuy() {
    setBuyLoading(true)
    setBuyResult(null)
    try {
      const res = await api.post('/api/topup/buy', {
        provider: selectedProvider,
        query: buyQuery,
      }, { timeout: 60000 })
      setBuyResult(res.data)
      if (res.data.code) {
        setRedeemCode(res.data.code)
      }
      api.get('/api/topup/history').then((r) => setHistory(r.data.history ?? [])).catch(() => {})
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      setBuyResult({ success: false, error: msg })
    } finally {
      setBuyLoading(false)
    }
  }

  // ─── Redeem ───────────────────────────────────────────────

  async function handleRedeem() {
    if (!redeemCode.trim() || !redeemBot) {
      alert('Введите код и выберите аккаунт')
      return
    }
    setRedeemLoading(true)
    setRedeemResult(null)
    try {
      const res = await api.post('/api/topup/redeem', {
        bot_name: redeemBot,
        code: redeemCode.trim(),
      })
      setRedeemResult(res.data)
      api.get('/api/topup/history').then((r) => setHistory(r.data.history ?? [])).catch(() => {})
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка'
      setRedeemResult({ success: false, message: msg })
    } finally {
      setRedeemLoading(false)
    }
  }

  // ─── Рендер ───────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col gap-6 p-6">
      <div className="flex items-center gap-3">
        <Wallet className="h-6 w-6 text-[hsl(var(--primary))]" />
        <h1 className="text-2xl font-bold">Пополнение баланса</h1>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
        {/* Левая колонка */}
        <div className="flex flex-col gap-4">
          {/* Провайдеры */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {providers.map((p) => (
              <button
                key={p.id}
                onClick={() => setSelectedProvider(p.id)}
                className={cn(
                  'rounded-lg border p-4 text-left transition-all',
                  selectedProvider === p.id
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.05)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:border-[hsl(var(--border-strong))]'
                )}
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-semibold">{p.name}</span>
                  {p.status === 'auto' ? (
                    <span className="rounded-full bg-green-500/20 px-1.5 py-0.5 text-[10px] text-green-400">API</span>
                  ) : p.status === 'manual' ? (
                    <span className="rounded-full bg-yellow-500/20 px-1.5 py-0.5 text-[10px] text-yellow-400">Ручной</span>
                  ) : (
                    <span className="rounded-full bg-[hsl(var(--muted))] px-1.5 py-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">Не настроен</span>
                  )}
                </div>
                <p className="text-xs text-[hsl(var(--muted-foreground))]">{p.description}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.payment_methods.map((m) => (
                    <span key={m} className="rounded bg-[hsl(var(--muted))] px-1.5 py-0.5 text-[10px]">{m}</span>
                  ))}
                </div>
              </button>
            ))}
          </div>

          {/* Цены провайдера */}
          {currentProvider && currentProvider.price_examples.length > 0 && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <h2 className="mb-3 font-semibold">Примерные цены — {currentProvider.name}</h2>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Номинал</TableHead>
                    <TableHead>Стоимость</TableHead>
                    <TableHead>Регион</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {currentProvider.price_examples.map((p, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">{p.denomination}</TableCell>
                      <TableCell>{p.approx_cost}</TableCell>
                      <TableCell className="text-[hsl(var(--muted-foreground))]">{p.region}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <a
                href={currentProvider.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs text-[hsl(var(--primary))] hover:underline"
              >
                <ExternalLink className="h-3 w-3" /> Открыть {currentProvider.name}
              </a>
            </div>
          )}

          {/* Покупка через API (G2A) */}
          {currentProvider?.status === 'auto' && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <h2 className="mb-3 flex items-center gap-2 font-semibold">
                <ShoppingCart className="h-4 w-4" /> Автоматическая покупка
              </h2>
              <div className="mb-3">
                <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Запрос (что искать)</label>
                <input
                  value={buyQuery} onChange={(e) => setBuyQuery(e.target.value)}
                  placeholder="Steam Wallet $5 USD"
                  className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                />
              </div>
              <Button loading={buyLoading} onClick={handleBuy}>
                <ShoppingCart className="h-4 w-4" /> Купить через {currentProvider.name}
              </Button>
              {buyResult && (
                <div className={cn('mt-3 rounded-md p-3 text-sm', buyResult.success ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400')}>
                  {buyResult.success ? (
                    <div className="flex items-center gap-2">
                      <CheckCircle className="h-4 w-4" />
                      <span>Код: <code className="rounded bg-black/30 px-2 py-0.5 font-mono">{buyResult.code}</code></span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <AlertCircle className="h-4 w-4" /> {buyResult.error}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Инструкция для ручных провайдеров */}
          {currentProvider?.status === 'manual' && (
            <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
              <h2 className="mb-2 font-semibold text-yellow-400">Ручная покупка</h2>
              <ol className="space-y-1 text-sm text-[hsl(var(--muted-foreground))]">
                <li>1. Перейдите на <a href={currentProvider.url} target="_blank" rel="noreferrer" className="text-[hsl(var(--primary))] hover:underline">{currentProvider.name}</a></li>
                <li>2. Найдите "Steam Wallet" нужного номинала</li>
                <li>3. Оплатите и получите код</li>
                <li>4. Вставьте код в поле «Активировать код» справа</li>
              </ol>
            </div>
          )}

          {/* История */}
          {history.length > 0 && (
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
              <h2 className="mb-3 font-semibold">История покупок</h2>
              <div className="max-h-48 overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Провайдер</TableHead>
                      <TableHead>Номинал</TableHead>
                      <TableHead>Код</TableHead>
                      <TableHead>Статус</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {history.map((h, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-xs">{h.provider}</TableCell>
                        <TableCell className="text-xs">{h.amount}</TableCell>
                        <TableCell className="font-mono text-xs">{h.code ?? '—'}</TableCell>
                        <TableCell>
                          {h.success ? (
                            <span className="text-xs text-green-400">
                              {h.redeemed_to.length > 0 ? `Активирован: ${h.redeemed_to.join(', ')}` : 'Куплен'}
                            </span>
                          ) : (
                            <span className="text-xs text-red-400">{h.error ?? 'Ошибка'}</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </div>

        {/* Правая колонка: активация */}
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h2 className="mb-3 flex items-center gap-2 font-semibold">
              <Key className="h-4 w-4" /> Активировать код
            </h2>
            <p className="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
              Вставьте Steam Wallet код (купленный на любом сервисе) и выберите аккаунт для активации через ASF.
            </p>

            <div className="mb-3">
              <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Steam Wallet код</label>
              <input
                value={redeemCode} onChange={(e) => setRedeemCode(e.target.value)}
                placeholder="XXXXX-XXXXX-XXXXX"
                className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 font-mono text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              />
            </div>

            <div className="mb-3">
              <label className="mb-1 block text-xs text-[hsl(var(--muted-foreground))]">Аккаунт (бот ASF)</label>
              <select
                value={redeemBot} onChange={(e) => setRedeemBot(e.target.value)}
                className="w-full rounded-md border border-[hsl(var(--border-strong))] bg-[hsl(var(--input))] px-3 py-2 text-sm"
              >
                <option value="">Выберите аккаунт</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.login}>{a.login}</option>
                ))}
              </select>
            </div>

            <Button
              className="w-full"
              loading={redeemLoading}
              disabled={!redeemCode.trim() || !redeemBot}
              onClick={handleRedeem}
            >
              <Key className="h-4 w-4" /> Активировать
            </Button>

            {redeemResult && (
              <div className={cn('mt-3 rounded-md p-3 text-sm', redeemResult.success ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400')}>
                {redeemResult.success ? (
                  <div className="flex items-center gap-2"><CheckCircle className="h-4 w-4" /> {redeemResult.message}</div>
                ) : (
                  <div className="flex items-center gap-2"><AlertCircle className="h-4 w-4" /> {redeemResult.message}</div>
                )}
              </div>
            )}
          </div>

          {/* Инфо */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 text-xs text-[hsl(var(--muted-foreground))]">
            <p className="mb-2 font-medium text-[hsl(var(--foreground))]">Как это работает</p>
            <ul className="space-y-1">
              <li>• <strong>G2A</strong> — автоматическая покупка через API (нужен G2A_API_KEY в .env)</li>
              <li>• <strong>BuySellVouchers</strong> — лучшие цены, ручная покупка, ввод кода</li>
              <li>• <strong>GGSEL</strong> — покупка из РФ, ручная покупка, ввод кода</li>
              <li>• Код активируется через ASF команду <code className="rounded bg-[hsl(var(--muted))] px-1">redeem</code></li>
              <li>• Один Wallet код = один аккаунт</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
