import { useState } from 'react'
import { useTheme, THEMES, type CustomTheme, type CustomThemeColors, getAutoColors } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { Plus, Trash2, Pencil, Check, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'

// Превью-цвета для встроенных тем
const themePreview: Record<string, { bg: string; sidebar: string; accent: string }> = {
  'dark-purple': { bg: '#141619', sidebar: '#101114', accent: '#5865F2' },
  'dark-green':  { bg: '#121716', sidebar: '#0e1310', accent: '#23a55a' },
  'dark-red':    { bg: '#121212', sidebar: '#0d0d0d', accent: '#e63956' },
  'light':       { bg: '#fafafa', sidebar: '#ffffff', accent: '#4752c4' },
}

// Дефолтные цвета для нового редактора
const DEFAULT_COLORS: CustomThemeColors = {
  background: '#1a1a2e',
  sidebar: '#16213e',
  accent: '#e94560',
}

// Лейблы полей цвета
const COLOR_LABELS: { key: keyof CustomThemeColors; label: string }[] = [
  { key: 'background', label: 'Фон' },
  { key: 'sidebar', label: 'Сайдбар' },
  { key: 'accent', label: 'Акцент' },
]

export function SettingsPage() {
  const { theme, setTheme, customThemes, addCustomTheme, deleteCustomTheme, updateCustomTheme } = useTheme()

  // Состояние редактора
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null) // null = создаём новую
  const [editorName, setEditorName] = useState('')
  const [editorColors, setEditorColors] = useState<CustomThemeColors>({ ...DEFAULT_COLORS })

  function openNewEditor() {
    setEditingId(null)
    setEditorName('')
    setEditorColors({ ...DEFAULT_COLORS })
    setEditorOpen(true)
  }

  function openEditEditor(t: CustomTheme) {
    setEditingId(t.id)
    setEditorName(t.name)
    setEditorColors({ ...t.colors })
    setEditorOpen(true)
  }

  function handleSave() {
    const name = editorName.trim() || 'Моя тема'
    if (editingId) {
      // Обновляем существующую
      updateCustomTheme({ id: editingId, name, colors: editorColors })
    } else {
      // Создаём новую
      const id = 'custom-' + Date.now()
      addCustomTheme({ id, name, colors: editorColors })
      setTheme(id)
    }
    setEditorOpen(false)
  }

  function handleColorChange(key: keyof CustomThemeColors, value: string) {
    setEditorColors((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-2xl font-bold mb-1">Настройки</h1>
      <p className="text-sm text-[hsl(var(--muted-foreground))] mb-6">
        Настройки приложения
      </p>

      {/* Секция: Тема */}
      <div className="rounded-lg border border-[hsl(var(--border-strong))] bg-[hsl(var(--card))] p-5">
        <h2 className="text-base font-semibold mb-1">Тема оформления</h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))] mb-4">
          Выберите внешний вид приложения
        </p>

        {/* Встроенные темы */}
        <div className="grid grid-cols-4 gap-3">
          {THEMES.map((t) => {
            const preview = themePreview[t.id]
            const isActive = theme === t.id

            return (
              <button
                key={t.id}
                onClick={() => setTheme(t.id)}
                className={cn(
                  'rounded-lg border-2 p-3 text-left cursor-pointer',
                  isActive
                    ? 'border-[hsl(var(--primary))] ring-2 ring-[hsl(var(--primary)/0.3)]'
                    : 'border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]'
                )}
              >
                {/* Миниатюра темы */}
                <div
                  className="rounded-md overflow-hidden mb-2 border border-[hsl(var(--border))]"
                  style={{ height: 64 }}
                >
                  <div className="flex h-full">
                    <div
                      className="w-1/4 h-full"
                      style={{ backgroundColor: preview.sidebar }}
                    >
                      <div
                        className="mt-3 mx-auto rounded-sm"
                        style={{ width: '60%', height: 4, backgroundColor: preview.accent }}
                      />
                      {[1, 2, 3].map((i) => (
                        <div
                          key={i}
                          className="mt-1.5 mx-auto rounded-sm opacity-30"
                          style={{
                            width: '60%', height: 3,
                            backgroundColor: t.id === 'light' ? '#333' : '#888',
                          }}
                        />
                      ))}
                    </div>
                    <div className="flex-1 h-full p-2" style={{ backgroundColor: preview.bg }}>
                      <div
                        className="rounded-sm mb-1"
                        style={{ width: '50%', height: 4, backgroundColor: t.id === 'light' ? '#222' : '#ccc', opacity: 0.7 }}
                      />
                      <div
                        className="rounded-sm"
                        style={{ width: '80%', height: 3, backgroundColor: '#666', opacity: 0.4 }}
                      />
                    </div>
                  </div>
                </div>
                <div className="text-sm font-medium">{t.label}</div>
              </button>
            )
          })}
        </div>

        {/* Кастомные темы */}
        {customThemes.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-[hsl(var(--muted-foreground))] mb-2">Мои темы</h3>
            <div className="grid grid-cols-3 gap-3">
              {customThemes.map((ct) => {
                const isActive = theme === ct.id
                const auto = getAutoColors(ct.colors.background)
                return (
                  <div
                    key={ct.id}
                    className={cn(
                      'rounded-lg border-2 p-3 text-left relative group',
                      isActive
                        ? 'border-[hsl(var(--primary))] ring-2 ring-[hsl(var(--primary)/0.3)]'
                        : 'border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]'
                    )}
                  >
                    {/* Кнопка выбрать */}
                    <button onClick={() => setTheme(ct.id)} className="w-full text-left cursor-pointer">
                      {/* Миниатюра */}
                      <div
                        className="rounded-md overflow-hidden mb-2 border border-[hsl(var(--border))]"
                        style={{ height: 64 }}
                      >
                        <div className="flex h-full">
                          <div className="w-1/4 h-full" style={{ backgroundColor: ct.colors.sidebar }}>
                            <div
                              className="mt-3 mx-auto rounded-sm"
                              style={{ width: '60%', height: 4, backgroundColor: ct.colors.accent }}
                            />
                            {[1, 2, 3].map((i) => (
                              <div
                                key={i}
                                className="mt-1.5 mx-auto rounded-sm opacity-30"
                                style={{ width: '60%', height: 3, backgroundColor: auto.text }}
                              />
                            ))}
                          </div>
                          <div className="flex-1 h-full p-2" style={{ backgroundColor: ct.colors.background }}>
                            <div
                              className="rounded-sm mb-1"
                              style={{ width: '50%', height: 4, backgroundColor: auto.text, opacity: 0.7 }}
                            />
                            <div
                              className="rounded-sm"
                              style={{ width: '80%', height: 3, backgroundColor: auto.text, opacity: 0.3 }}
                            />
                          </div>
                        </div>
                      </div>
                      <div className="text-sm font-medium">{ct.name}</div>
                    </button>

                    {/* Кнопки редактировать / удалить */}
                    <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100">
                      <button
                        onClick={() => openEditEditor(ct)}
                        className="p-1 rounded bg-[hsl(var(--muted))] hover:bg-[hsl(var(--accent))] cursor-pointer"
                        title="Редактировать"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => deleteCustomTheme(ct.id)}
                        className="p-1 rounded bg-[hsl(var(--muted))] hover:bg-[hsl(var(--destructive)/0.3)] cursor-pointer"
                        title="Удалить"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Кнопка создать тему */}
        {!editorOpen && (
          <button
            onClick={openNewEditor}
            className="mt-4 w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border-2 border-dashed border-[hsl(var(--border-strong))] text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:border-[hsl(var(--primary)/0.5)] cursor-pointer"
          >
            <Plus className="h-4 w-4" />
            Создать свою тему
          </button>
        )}

        {/* Редактор темы */}
        {editorOpen && (
          <div className="mt-4 rounded-lg border border-[hsl(var(--border-strong))] bg-[hsl(var(--background-secondary))] p-4">
            <h3 className="text-sm font-semibold mb-3">
              {editingId ? 'Редактировать тему' : 'Новая тема'}
            </h3>

            {/* Название */}
            <div className="mb-4">
              <label className="text-xs text-[hsl(var(--muted-foreground))] mb-1 block">Название</label>
              <input
                type="text"
                value={editorName}
                onChange={(e) => setEditorName(e.target.value)}
                placeholder="Моя тема"
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
              />
            </div>

            {/* Цвета */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {COLOR_LABELS.map(({ key, label }) => (
                <div key={key}>
                  <label className="text-xs text-[hsl(var(--muted-foreground))] mb-1 block">{label}</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={editorColors[key]}
                      onChange={(e) => handleColorChange(key, e.target.value)}
                      className="h-8 w-8 rounded cursor-pointer border border-[hsl(var(--border))] bg-transparent p-0"
                    />
                    <input
                      type="text"
                      value={editorColors[key]}
                      onChange={(e) => {
                        const v = e.target.value
                        if (/^#[0-9a-fA-F]{0,6}$/.test(v)) handleColorChange(key, v)
                      }}
                      className="flex-1 min-w-0 rounded border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-2 py-1 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Превью */}
            <div className="mb-4">
              <label className="text-xs text-[hsl(var(--muted-foreground))] mb-1 block">Превью</label>
              {(() => {
                const preview = getAutoColors(editorColors.background)
                const sidebarPreview = getAutoColors(editorColors.sidebar)
                return (
                  <div
                    className="rounded-lg overflow-hidden border border-[hsl(var(--border))]"
                    style={{ height: 80 }}
                  >
                    <div className="flex h-full">
                      {/* Sidebar */}
                      <div className="w-1/4 h-full p-2" style={{ backgroundColor: editorColors.sidebar }}>
                        <div className="rounded-sm mb-1.5" style={{ height: 5, backgroundColor: editorColors.accent }} />
                        {[1, 2, 3].map((i) => (
                          <div
                            key={i}
                            className="rounded-sm mb-1"
                            style={{ height: 4, backgroundColor: sidebarPreview.text, opacity: 0.25 }}
                          />
                        ))}
                      </div>
                      {/* Content */}
                      <div className="flex-1 h-full p-3" style={{ backgroundColor: editorColors.background }}>
                        {/* Card */}
                        <div
                          className="rounded p-2 h-full"
                          style={{ backgroundColor: preview.card }}
                        >
                          <div className="rounded-sm mb-1.5" style={{ width: '40%', height: 5, backgroundColor: preview.text, opacity: 0.8 }} />
                          <div className="rounded-sm mb-2" style={{ width: '70%', height: 4, backgroundColor: preview.text, opacity: 0.3 }} />
                          <div className="rounded-sm" style={{ width: '25%', height: 6, backgroundColor: editorColors.accent, borderRadius: 3 }} />
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })()}
            </div>

            {/* Кнопки */}
            <div className="flex gap-2">
              <Button variant="primary" size="sm" onClick={handleSave}>
                <Check className="h-3.5 w-3.5" />
                {editingId ? 'Сохранить' : 'Создать'}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setEditorOpen(false)}>
                <X className="h-3.5 w-3.5" />
                Отмена
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Заглушка для других настроек */}
      <div className="mt-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
        <h2 className="text-base font-semibold mb-1">Другие настройки</h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Дополнительные настройки будут добавлены в следующих фазах
        </p>
      </div>
    </div>
  )
}
