import { Pickaxe } from 'lucide-react'

export function FarmPage() {
  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-1">
        <Pickaxe className="h-6 w-6 text-[hsl(var(--primary))]" />
        <h1 className="text-2xl font-bold">Фарм</h1>
      </div>
      <p className="text-sm text-[hsl(var(--muted-foreground))] mb-6">
        Управление фармом аккаунтов
      </p>

      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
        <Pickaxe className="h-10 w-10 mx-auto mb-3 text-[hsl(var(--muted-foreground))] opacity-40" />
        <p className="text-[hsl(var(--muted-foreground))]">
          Модуль в разработке — Фаза 4
        </p>
      </div>
    </div>
  )
}
