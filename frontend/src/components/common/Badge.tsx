import type { ReactNode } from 'react'

const variants = {
  default: 'border-ink-700 bg-ink-800/60 text-ink-300',
  live: 'border-teal-accent/35 bg-teal-soft text-teal-accent',
  warn: 'border-gate-escalate/40 bg-gate-escalate/10 text-gate-escalate',
  danger: 'border-gate-deny/40 bg-gate-deny/10 text-gate-deny',
  ok: 'border-gate-approve/40 bg-gate-approve/10 text-gate-approve',
  muted: 'border-ink-700 text-ink-500',
} as const

export function Badge({
  children,
  variant = 'default',
  className = '',
}: {
  children: ReactNode
  variant?: keyof typeof variants
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-[0.7rem] ${variants[variant]} ${className}`}
    >
      {children}
    </span>
  )
}
