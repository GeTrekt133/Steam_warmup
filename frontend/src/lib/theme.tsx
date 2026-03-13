import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

// ─── Встроенные темы ────────────────────────────────────────

export const THEMES = [
  { id: 'dark-purple', label: 'Тёмная (фиолетовая)', icon: '🟣' },
  { id: 'dark-green', label: 'Тёмная (зелёная)', icon: '🟢' },
  { id: 'dark-red', label: 'Тёмная (красная)', icon: '🔴' },
  { id: 'light', label: 'Светлая', icon: '⚪' },
] as const

export type BuiltinThemeId = (typeof THEMES)[number]['id']
export type ThemeId = BuiltinThemeId | string // string — для кастомных тем (custom-xxx)

// ─── Кастомные темы ─────────────────────────────────────────

// Пользователь выбирает 3 основных цвета, текст и карточки генерируются автоматически
export interface CustomThemeColors {
  background: string   // HEX — основной фон
  sidebar: string      // HEX — фон сайдбара
  accent: string       // HEX — акцентный цвет (кнопки, ссылки)
}

export interface CustomTheme {
  id: string           // 'custom-1678...'
  name: string         // пользовательское название
  colors: CustomThemeColors
}

const CUSTOM_THEMES_KEY = 'custom_themes'

export function loadCustomThemes(): CustomTheme[] {
  try {
    const raw = localStorage.getItem(CUSTOM_THEMES_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

export function saveCustomThemes(themes: CustomTheme[]) {
  localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(themes))
}

// ─── HEX ↔ HSL конвертация ──────────────────────────────────

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ]
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255
  const max = Math.max(r, g, b), min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l * 100]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max - min)
  let h = 0
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6
  else if (max === g) h = ((b - r) / d + 2) / 6
  else h = ((r - g) / d + 4) / 6
  return [Math.round(h * 360), Math.round(s * 100), Math.round(l * 100)]
}

/** HEX → "H S% L%" строка для CSS-переменных */
export function hexToHslString(hex: string): string {
  const [r, g, b] = hexToRgb(hex)
  const [h, s, l] = rgbToHsl(r, g, b)
  return `${h} ${s}% ${l}%`
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h /= 360; s /= 100; l /= 100
  if (s === 0) { const v = Math.round(l * 255); return [v, v, v] }
  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1; if (t > 1) t -= 1
    if (t < 1/6) return p + (q - p) * 6 * t
    if (t < 1/2) return q
    if (t < 2/3) return p + (q - p) * (2/3 - t) * 6
    return p
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  return [
    Math.round(hue2rgb(p, q, h + 1/3) * 255),
    Math.round(hue2rgb(p, q, h) * 255),
    Math.round(hue2rgb(p, q, h - 1/3) * 255),
  ]
}

/** "H S% L%" → "#rrggbb" */
export function hslStringToHex(hslStr: string): string {
  const parts = hslStr.replace(/%/g, '').split(/\s+/).map(Number)
  const [r, g, b] = hslToRgb(parts[0], parts[1], parts[2])
  return '#' + [r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')
}

/** Сдвигает lightness HSL-строки */
function adjustL(hsl: string, delta: number): string {
  const parts = hsl.replace(/%/g, '').split(/\s+/).map(Number)
  const newL = Math.max(0, Math.min(100, parts[2] + delta))
  return `${parts[0]} ${parts[1]}% ${newL}%`
}

/** Определяет, светлый ли цвет (для выбора foreground) */
function isLight(hex: string): boolean {
  const [r, g, b] = hexToRgb(hex)
  return (r * 299 + g * 587 + b * 114) / 1000 > 128
}

/** Вычисляет авто-цвета текста и карточки из фона (для превью) */
export function getAutoColors(bgHex: string): { text: string; card: string } {
  const light = isLight(bgHex)
  const bgHsl = hexToHslString(bgHex)
  return {
    text: hslStringToHex(adjustL(bgHsl, light ? -75 : 75)),
    card: hslStringToHex(adjustL(bgHsl, light ? -4 : 4)),
  }
}

// ─── Генерация всех CSS-переменных из 3 цветов ──────────────

export function generateCssVars(colors: CustomThemeColors): Record<string, string> {
  const bg = hexToHslString(colors.background)
  const sidebar = hexToHslString(colors.sidebar)
  const accent = hexToHslString(colors.accent)

  const lightBg = isLight(colors.background)
  const fgOnAccent = isLight(colors.accent) ? '0 0% 0%' : '0 0% 100%'

  // Текст — всегда контрастный к фону (авто)
  const text = lightBg ? adjustL(bg, -75) : adjustL(bg, 75)
  // Карточка — чуть светлее/темнее фона (авто)
  const card = adjustL(bg, lightBg ? -4 : 4)

  // Muted текст — приглушённая версия
  const mutedText = lightBg ? adjustL(bg, -35) : adjustL(bg, 40)
  // Вторичный фон
  const bgSecondary = adjustL(bg, lightBg ? -3 : 3)
  const bgTertiary = adjustL(bg, lightBg ? 2 : -2)
  // Бордеры
  const border = adjustL(bg, lightBg ? -8 : 7)
  const borderStrong = adjustL(bg, lightBg ? -15 : 13)
  const input = adjustL(bg, lightBg ? -10 : 9)
  // Secondary / Accent bg
  const secondary = adjustL(bg, lightBg ? -4 : 9)
  const secondaryFg = adjustL(text, lightBg ? 5 : -5)
  const accentBg = adjustL(bg, lightBg ? -6 : 7)

  // Popover
  const popover = adjustL(bg, lightBg ? 1 : 2)
  // Muted bg
  const muted = adjustL(bg, lightBg ? -3 : 11)

  // Sidebar производные
  const lightSidebar = isLight(colors.sidebar)
  const sidebarBorder = adjustL(sidebar, lightSidebar ? -6 : 4)
  const sidebarAccent = adjustL(sidebar, lightSidebar ? -4 : 7)
  const sidebarFg = lightSidebar ? adjustL(sidebar, -70) : adjustL(sidebar, 70)

  return {
    '--background': bg,
    '--background-secondary': bgSecondary,
    '--background-tertiary': bgTertiary,
    '--card': card,
    '--card-foreground': text,
    '--popover': popover,
    '--popover-foreground': text,
    '--foreground': text,
    '--muted': muted,
    '--muted-foreground': mutedText,
    '--primary': accent,
    '--primary-foreground': fgOnAccent,
    '--secondary': secondary,
    '--secondary-foreground': secondaryFg,
    '--accent': accentBg,
    '--accent-foreground': text,
    '--success': '145 65% 42%',
    '--success-foreground': '0 0% 100%',
    '--warning': '38 95% 60%',
    '--warning-foreground': '0 0% 8%',
    '--destructive': '0 70% 50%',
    '--destructive-foreground': '0 0% 100%',
    '--border': border,
    '--border-strong': borderStrong,
    '--input': input,
    '--ring': accent,
    '--radius': '0.5rem',
    '--sidebar-background': sidebar,
    '--sidebar-foreground': sidebarFg,
    '--sidebar-primary': accent,
    '--sidebar-primary-foreground': fgOnAccent,
    '--sidebar-accent': sidebarAccent,
    '--sidebar-accent-foreground': text,
    '--sidebar-border': sidebarBorder,
    '--sidebar-ring': accent,
  }
}

// ─── Применение кастомной темы к DOM ─────────────────────────

function applyCustomTheme(colors: CustomThemeColors) {
  const vars = generateCssVars(colors)
  const root = document.documentElement
  root.setAttribute('data-theme', 'custom')
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value)
  }
}

function clearCustomThemeVars() {
  const root = document.documentElement
  root.style.cssText = ''
}

// ─── Контекст темы ──────────────────────────────────────────

interface ThemeContextValue {
  theme: ThemeId
  setTheme: (theme: ThemeId) => void
  customThemes: CustomTheme[]
  addCustomTheme: (theme: CustomTheme) => void
  deleteCustomTheme: (id: string) => void
  updateCustomTheme: (theme: CustomTheme) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const STORAGE_KEY = 'app_theme'

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(() => {
    return localStorage.getItem(STORAGE_KEY) || 'dark-purple'
  })

  const [customThemes, setCustomThemes] = useState<CustomTheme[]>(() => loadCustomThemes())

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, theme)

    // Если это кастомная тема — применяем CSS-переменные через JS
    const custom = customThemes.find((t) => t.id === theme)
    if (custom) {
      applyCustomTheme(custom.colors)
    } else {
      // Встроенная тема — убираем inline-стили и ставим data-theme
      clearCustomThemeVars()
      document.documentElement.setAttribute('data-theme', theme)
    }
  }, [theme, customThemes])

  function setTheme(newTheme: ThemeId) {
    setThemeState(newTheme)
  }

  function addCustomTheme(t: CustomTheme) {
    const updated = [...customThemes, t]
    setCustomThemes(updated)
    saveCustomThemes(updated)
  }

  function deleteCustomTheme(id: string) {
    const updated = customThemes.filter((t) => t.id !== id)
    setCustomThemes(updated)
    saveCustomThemes(updated)
    // Если удаляем активную тему — переключаемся на дефолт
    if (theme === id) setTheme('dark-purple')
  }

  function updateCustomTheme(t: CustomTheme) {
    const updated = customThemes.map((ct) => (ct.id === t.id ? t : ct))
    setCustomThemes(updated)
    saveCustomThemes(updated)
  }

  return (
    <ThemeContext.Provider value={{ theme, setTheme, customThemes, addCustomTheme, deleteCustomTheme, updateCustomTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
