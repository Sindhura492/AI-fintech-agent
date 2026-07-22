export function formatMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '-'
  return `$${Number(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function formatPercent(rate: number | null | undefined): string {
  return `${(Number(rate || 0) * 100).toFixed(1)}%`
}

export function formatSessionShort(id: string | null | undefined): string {
  if (!id) return '-'
  return `${id.slice(0, 8)}…`
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '-'
  return iso.replace('T', ' ').slice(0, 19)
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '-'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return iso
  const diffSec = Math.round((now - t) / 1000)
  if (diffSec < 5) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 48) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  return `${diffDay}d ago`
}
