import { useState, type FormEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import api from '@/lib/api'

export function RegisterPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')

    if (password !== confirmPassword) {
      setError('Пароли не совпадают')
      return
    }

    setLoading(true)

    try {
      const res = await api.post('/api/auth/register', { username, password })
      localStorage.setItem('auth_token', res.data.access_token)
      navigate('/')
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } }
        setError(axiosErr.response?.data?.detail ?? 'Ошибка регистрации')
      } else {
        setError('Сервер недоступен')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[hsl(var(--background))]">
      <div className="w-full max-w-sm rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8">
        <h1 className="text-xl font-bold mb-1">Регистрация</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))] mb-6">Создайте аккаунт для панели</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1.5">Логин</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--input))] bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              required
              minLength={3}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Пароль</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--input))] bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              required
              minLength={6}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Подтвердите пароль</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full rounded-md border border-[hsl(var(--input))] bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
              required
            />
          </div>

          {error && (
            <div className="text-sm text-red-400 bg-red-400/10 rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {loading ? 'Регистрация...' : 'Зарегистрироваться'}
          </button>
        </form>

        <p className="text-sm text-[hsl(var(--muted-foreground))] mt-4 text-center">
          Уже есть аккаунт?{' '}
          <Link to="/login" className="text-[hsl(var(--foreground))] underline">
            Войти
          </Link>
        </p>
      </div>
    </div>
  )
}
