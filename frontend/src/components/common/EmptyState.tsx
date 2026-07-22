import type { LucideIcon } from 'lucide-react'

export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon?: LucideIcon
  title: string
  description?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      {Icon ? <Icon className="mb-3 h-6 w-6 text-ink-500" strokeWidth={1.5} /> : null}
      <p className="text-sm font-medium text-ink-300">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-sm text-ink-500">{description}</p>
      ) : null}
    </div>
  )
}
