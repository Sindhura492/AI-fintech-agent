import { Panel } from '@/components/common/Panel'
import { usePipeline } from '@/hooks/usePipeline'
import { formatPercent } from '@/lib/format'

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-paper-edge bg-paper p-4 shadow-panel">
      <div className="font-mono text-[0.65rem] uppercase tracking-wide text-ink-500">
        {label}
      </div>
      <div className="mt-1 font-display text-2xl font-semibold text-ink-100">{value}</div>
    </div>
  )
}

function BarRow({
  label,
  value,
  max,
  color,
}: {
  label: string
  value: number
  max: number
  color: string
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-ink-500">
        <span>{label}</span>
        <span className="font-mono text-ink-300">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ink-800">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function MetricsOverview() {
  const { metrics, metricsError } = usePipeline()
  const counts = metrics?.step_counts_by_type || {}
  const latency = metrics?.avg_latency_per_step_type_ms || {}
  const health = metrics?.health || []
  const series = metrics?.rate_series
  const maxSteps = Math.max(counts.llm || 0, counts.deterministic || 0, counts.ml || 0, 1)
  const maxLat = Math.max(
    latency.llm || 0,
    latency.deterministic || 0,
    latency.ml || 0,
    1,
  )

  return (
    <div className="space-y-4">
      {metricsError ? (
        <p className="text-sm text-gate-deny">Metrics unavailable: {metricsError}</p>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Total runs" value={String(metrics?.total_runs ?? 0)} />
        <Stat label="Escalation rate" value={formatPercent(metrics?.escalation_rate)} />
        <Stat label="Anomaly flag rate" value={formatPercent(metrics?.anomaly_flag_rate)} />
        <Stat label="LLM calls" value={String(metrics?.total_llm_calls ?? 0)} />
      </div>

      <Panel title="Health - recent runs">
        <div className="mb-2 flex flex-wrap gap-1.5" aria-label="Recent run health">
          {health.length === 0 ? (
            <span className="text-sm text-ink-500">No runs recorded yet.</span>
          ) : (
            health.map((h, i) => {
              let cls = 'bg-gate-approve'
              if (!h.success || h.outcome === 'failed' || h.outcome === 'denied') {
                cls = 'bg-gate-deny'
              } else if (h.outcome === 'escalated') {
                cls = 'bg-gate-escalate'
              }
              return (
                <span
                  key={`${h.session_id}-${i}`}
                  title={`${h.outcome} · ${h.session_id}`}
                  className={`h-3.5 w-3.5 rounded-sm ${cls}`}
                />
              )
            })
          )}
        </div>
        <p className="text-xs text-ink-500">
          Green = success · Yellow = escalated · Red = failed / denied
        </p>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Step count by type">
          <div className="space-y-3">
            <BarRow label="LLM" value={counts.llm || 0} max={maxSteps} color="bg-[var(--llm)]" />
            <BarRow
              label="Deterministic"
              value={counts.deterministic || 0}
              max={maxSteps}
              color="bg-teal-accent"
            />
            <BarRow label="ML" value={counts.ml || 0} max={maxSteps} color="bg-[var(--ml)]" />
          </div>
        </Panel>

        <Panel title="Avg latency per step type (ms)">
          <div className="space-y-3">
            <BarRow
              label="LLM"
              value={Number(latency.llm || 0)}
              max={maxLat}
              color="bg-[var(--llm)]/80"
            />
            <BarRow
              label="Deterministic"
              value={Number(latency.deterministic || 0)}
              max={maxLat}
              color="bg-teal-accent/80"
            />
            <BarRow
              label="ML"
              value={Number(latency.ml || 0)}
              max={maxLat}
              color="bg-[var(--ml)]/80"
            />
          </div>
        </Panel>
      </div>

      {series && (series.labels?.length || 0) > 0 ? (
        <Panel title="Escalation & anomaly rates (recent)">
          <div className="space-y-2 text-xs text-ink-500">
            <div className="flex gap-4">
              <span className="text-gate-escalate">● Escalation</span>
              <span className="text-[var(--ml)]">● Anomaly</span>
            </div>
            <div className="flex h-24 items-end gap-0.5">
              {(series.labels || []).map((_, i) => {
                const esc = (series.escalation_rate || [])[i] || 0
                const anom = (series.anomaly_flag_rate || [])[i] || 0
                return (
                  <div key={i} className="flex h-full flex-1 flex-col justify-end gap-0.5">
                    <div
                      className="w-full rounded-t-sm bg-gate-escalate/80"
                      style={{ height: `${esc * 100}%`, minHeight: esc > 0 ? 2 : 0 }}
                      title={`esc ${(esc * 100).toFixed(0)}%`}
                    />
                    <div
                      className="w-full rounded-t-sm bg-[var(--ml)]/70"
                      style={{ height: `${anom * 100}%`, minHeight: anom > 0 ? 2 : 0 }}
                      title={`anom ${(anom * 100).toFixed(0)}%`}
                    />
                  </div>
                )
              })}
            </div>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}
