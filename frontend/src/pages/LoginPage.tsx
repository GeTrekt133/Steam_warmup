import { useState, type FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { loginUser } from '@/lib/auth'
import { Button } from '@/components/ui/Button'

export function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const result = await loginUser(username, password)
      if (result.success) {
        navigate('/')
      } else {
        setError(result.error ?? 'Ошибка входа')
      }
    } catch {
      setError('Произошла ошибка при входе')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[hsl(var(--background-tertiary))]">
      <div className="w-full max-w-sm rounded-lg border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] p-8 shadow-2xl">
        <h1 className="text-xl font-bold mb-1">Selik где деньги</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))] mb-6">Войдите в аккаунт</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1.5 text-[hsl(var(--muted-foreground))]">Логин</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] placeholder:text-[hsl(var(--muted-foreground)/0.5)]"
              placeholder="Введите логин"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5 text-[hsl(var(--muted-foreground))]">Пароль</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] placeholder:text-[hsl(var(--muted-foreground)/0.5)]"
              placeholder="Введите пароль"
              required
            />
          </div>

          {error && (
            <div className="text-sm text-[hsl(var(--destructive-foreground))] bg-[hsl(var(--destructive)/0.15)] border border-[hsl(var(--destructive)/0.3)] rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <Button type="submit" loading={loading} className="w-full">
            {loading ? 'Вход...' : 'Войти'}
          </Button>
        </form>

        <p className="text-sm text-[hsl(var(--muted-foreground))] mt-4 text-center">
          Нет аккаунта?{' '}
          <Link to="/register" className="text-[hsl(var(--primary))] hover:underline">
            Зарегистрироваться
          </Link>
        </p>
      </div>
    </div>
  )
}
