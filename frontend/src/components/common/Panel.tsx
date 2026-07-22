import type { ReactNode } from 'react'

export function Panel({
  children,
  className = '',
  title,
  action,
}: {
  children: ReactNode
  className?: string
  title?: string
  action?: ReactNode
}) {
  return (
    <section
      className={`rounded-xl border border-paper-edge bg-paper shadow-panel ${className}`}
    >
      {(title || action) && (
        <div className="flex items-center justify-between gap-3 border-b border-ink-700/80 px-4 py-3">
          {title ? (
            <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-500">
              {title}
            </h2>
          ) : (
            <span />
          )}
          {action}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}
