import { usePipeline } from '@/hooks/usePipeline'
import { formatMoney } from '@/lib/format'

export function OutcomeBanner() {
  const { gate, settlement } = usePipeline()

  if (!gate && !settlement) return null

  const action = gate?.action
  const gateStyles =
    action === 'approve'
      ? 'border-gate-approve/50 bg-gate-approve/10 text-gate-approve'
      : action === 'deny'
        ? 'border-gate-deny/50 bg-gate-deny/10 text-gate-deny'
        : action === 'escalate'
          ? 'border-gate-escalate/50 bg-gate-escalate/10 text-gate-escalate'
          : 'border-ink-700 bg-ink-800 text-ink-300'

  return (
    <div className="mb-4 space-y-3">
      {settlement ? (
        <div
          className={`rounded-xl border px-4 py-4 text-center shadow-panel ${
            settlement.converged
              ? 'border-gate-approve/40 bg-gate-approve/10'
              : 'border-gate-escalate/40 bg-gate-escalate/10'
          }`}
          aria-live="polite"
        >
          <div className="font-display text-lg font-semibold text-ink-100">
            {settlement.converged ? 'Settlement reached' : 'No convergence - escalated'}
          </div>
          <div className="mt-1 text-sm text-ink-300">
            {settlement.converged
              ? settlement.amount != null
                ? `Agreed amount ${formatMoney(settlement.amount)}`
                : 'Both sides aligned'
              : 'Handing off to enforcement / human review'}
          </div>
        </div>
      ) : null}

      {gate ? (
        <div
          className={`rounded-xl border px-4 py-5 text-center shadow-panel ${gateStyles}`}
          aria-live="polite"
        >
          <div className="font-display text-4xl font-bold tracking-[0.12em] sm:text-5xl">
            {gate.label || String(gate.action || '').toUpperCase()}
          </div>
          <div className="mt-2 font-mono text-xs text-ink-300">
            rule_fired: <strong className="text-ink-100">{gate.rule_fired || '-'}</strong>
          </div>
          {gate.reason ? (
            <div className="mt-2 text-sm text-ink-300">{gate.reason}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
