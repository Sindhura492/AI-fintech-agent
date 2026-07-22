import { Panel } from '@/components/common/Panel'
import { usePipeline } from '@/hooks/usePipeline'
import { formatMoney, formatSessionShort, formatTimestamp } from '@/lib/format'

const outcomeClass: Record<string, string> = {
  approved: 'border-gate-approve/40 text-gate-approve',
  denied: 'border-gate-deny/40 text-gate-deny',
  escalated: 'border-gate-escalate/40 text-gate-escalate',
  failed: 'border-gate-deny/40 text-gate-deny',
}

export function RunsTable() {
  const { metrics } = usePipeline()
  const runs = metrics?.recent_runs || []

  return (
    <Panel className="mt-4" title="Run log">
      <div className="overflow-x-auto rounded-lg border border-ink-700">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-ink-700 bg-ink-900/80">
              {['Time', 'Vendor', 'Amount', 'Outcome', 'Session'].map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 font-mono text-[0.65rem] font-medium uppercase tracking-wide text-ink-500"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-4 text-ink-500">
                  No runs yet - execute a pipeline to populate metrics.
                </td>
              </tr>
            ) : (
              runs.map((r, i) => (
                <tr
                  key={`${r.session_id}-${i}`}
                  className="border-b border-ink-700/80 last:border-0"
                >
                  <td className="whitespace-nowrap px-3 py-2.5 text-ink-300">
                    {formatTimestamp(r.timestamp)}
                  </td>
                  <td className="px-3 py-2.5 text-ink-100">{r.vendor || '-'}</td>
                  <td className="px-3 py-2.5 font-mono text-ink-300">
                    {formatMoney(r.amount)}
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={`rounded-full border px-2 py-0.5 font-mono text-[0.68rem] ${
                        outcomeClass[r.outcome || ''] || 'border-ink-700 text-ink-500'
                      }`}
                    >
                      {r.outcome || '-'}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-ink-500">
                    {formatSessionShort(r.session_id)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
