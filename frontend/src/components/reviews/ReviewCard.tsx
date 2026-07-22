import { Check, X } from 'lucide-react'
import { formatMoney } from '@/lib/format'
import type { ReviewItem, ReviewKind } from '@/types/pipeline'

function isPending(item: ReviewItem): boolean {
  return (
    item.status === 'pending' ||
    item.status === 'pending_review' ||
    (!item.status && !item.action && !item.resolved_action)
  )
}

function isApproved(item: ReviewItem): boolean {
  const action = (item.action || item.resolved_action || '').toLowerCase()
  return action === 'approve' || item.status === 'approved'
}

export function ReviewCard({
  item,
  resolving,
  onResolve,
}: {
  item: ReviewItem
  resolving: boolean
  onResolve: (kind: ReviewKind, sessionId: string, action: 'approve' | 'deny') => void
}) {
  const pending = isPending(item)
  const approved = isApproved(item)
  const isAnomaly = item.kind === 'anomaly'

  const border = pending
    ? isAnomaly
      ? 'border-[var(--ml)]/40'
      : 'border-gate-escalate/40'
    : approved
      ? 'border-gate-approve/40'
      : 'border-gate-deny/40'

  const title = pending
    ? isAnomaly
      ? 'Anomaly flagged - approve to continue'
      : 'Escalation - approval needed'
    : isAnomaly
      ? approved
        ? 'Anomaly cleared by human'
        : 'Anomaly confirmed by human'
      : approved
        ? 'Escalation approved by human'
        : 'Escalation denied by human'

  let statusText = ''
  if (!pending) {
    if (isAnomaly) {
      statusText = approved
        ? 'Anomaly cleared - pipeline resumed (negotiate / gate).'
        : 'Anomaly confirmed - pipeline stopped, payment blocked.'
    } else {
      statusText = approved
        ? item.payment_executed
          ? 'Payment executed after human approval.'
          : 'Approved - no payment (no settlement on file).'
        : 'Payment blocked - human denied.'
    }
  }

  return (
    <article className={`rounded-xl border bg-ink-900/60 p-4 ${border}`}>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink-100">{title}</h3>
        <span className="rounded-full border border-ink-700 px-2 py-0.5 font-mono text-[0.65rem] text-ink-500">
          {isAnomaly ? 'ML anomaly' : 'Gate escalate'}
        </span>
      </div>
      <div className="text-sm text-ink-300">
        <strong className="text-ink-100">{item.vendor_name || 'Unknown vendor'}</strong>
        {' · '}
        {formatMoney(item.amount)}
        {isAnomaly ? (
          <>
            <div className="mt-1 font-mono text-xs text-ink-500">
              score={item.anomaly_score ?? '-'} · {item.method || 'isolation_forest'}
            </div>
            {item.explanation ? <div className="mt-1">{item.explanation}</div> : null}
          </>
        ) : (
          <div className="mt-1 text-xs text-ink-500">
            {item.display_reason || item.reason || 'escalated'}
            {item.rule_fired ? ` · ${item.rule_fired}` : ''}
          </div>
        )}
      </div>

      {pending ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={resolving}
            onClick={() => onResolve(item.kind, item.session_id, 'approve')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gate-approve/40 bg-gate-approve/15 px-3 py-1.5 text-sm font-semibold text-gate-approve disabled:opacity-50"
          >
            <Check className="h-4 w-4" />
            {isAnomaly ? 'Clear & continue' : 'Approve'}
          </button>
          <button
            type="button"
            disabled={resolving}
            onClick={() => onResolve(item.kind, item.session_id, 'deny')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gate-deny/40 bg-gate-deny/15 px-3 py-1.5 text-sm font-semibold text-gate-deny disabled:opacity-50"
          >
            <X className="h-4 w-4" />
            {isAnomaly ? 'Block payment' : 'Deny'}
          </button>
          {resolving ? (
            <span className="self-center text-xs text-ink-500">Resolving…</span>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-500">{statusText}</p>
      )}
    </article>
  )
}
