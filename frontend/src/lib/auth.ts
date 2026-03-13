// Локальная авторизация через localStorage
// Пользователи хранятся в localStorage, пароли хешируются через SHA-256

interface StoredUser {
  username: string
  passwordHash: string
  createdAt: string
}

const USERS_KEY = 'panel_users'
const TOKEN_KEY = 'auth_token'
const CURRENT_USER_KEY = 'current_user'

function getUsers(): StoredUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveUsers(users: StoredUser[]) {
  localStorage.setItem(USERS_KEY, JSON.stringify(users))
}

// Простое хеширование пароля (SHA-256 через SubtleCrypto)
async function hashPassword(password: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(password + '_steam_panel_salt')
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

// Генерация простого токена
function generateToken(username: string): string {
  const payload = btoa(JSON.stringify({ username, ts: Date.now() }))
  return `local_${payload}`
}

export function getCurrentUser(): string | null {
  return localStorage.getItem(CURRENT_USER_KEY)
}

export async function registerUser(username: string, password: string): Promise<{ success: boolean; error?: string }> {
  const users = getUsers()

  if (users.some(u => u.username.toLowerCase() === username.toLowerCase())) {
    return { success: false, error: 'Пользователь с таким логином уже существует' }
  }

  const passwordHash = await hashPassword(password)
  users.push({
    username,
    passwordHash,
    createdAt: new Date().toISOString(),
  })
  saveUsers(users)

  // Автоматически входим после регистрации
  const token = generateToken(username)
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(CURRENT_USER_KEY, username)

  return { success: true }
}

export async function loginUser(username: string, password: string): Promise<{ success: boolean; error?: string }> {
  const users = getUsers()
  const user = users.find(u => u.username.toLowerCase() === username.toLowerCase())

  if (!user) {
    return { success: false, error: 'Пользователь не найден' }
  }

  const passwordHash = await hashPassword(password)
  if (user.passwordHash !== passwordHash) {
    return { success: false, error: 'Неверный пароль' }
  }

  const token = generateToken(username)
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(CURRENT_USER_KEY, username)

  return { success: true }
}

export function logoutUser() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(CURRENT_USER_KEY)
}

export function isLoggedIn(): boolean {
  return !!localStorage.getItem(TOKEN_KEY)
}
