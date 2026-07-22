import { ListTree } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { usePipeline } from '@/hooks/usePipeline'

const typeStyles: Record<string, string> = {
  llm: 'border-l-[var(--llm)] text-[var(--llm)]',
  ml: 'border-l-[var(--ml)] text-[var(--ml)]',
  deterministic: 'border-l-teal-accent text-teal-accent',
}

const typeLabels: Record<string, string> = {
  llm: 'LLM',
  ml: 'ML',
  deterministic: 'Rule',
}

export function StepTimeline() {
  const { auditEntries } = usePipeline()

  return (
    <details className="group mb-4 rounded-xl border border-paper-edge bg-paper shadow-panel">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-ink-300 marker:content-none [&::-webkit-details-marker]:hidden">
        <span className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <ListTree className="h-4 w-4 text-ink-500" />
            What the system did
            <span className="font-mono text-xs text-ink-500">
              ({auditEntries.length} steps)
            </span>
          </span>
          <span className="text-xs text-ink-500 group-open:hidden">Show trace</span>
          <span className="hidden text-xs text-ink-500 group-open:inline">Hide trace</span>
        </span>
      </summary>
      <div className="border-t border-ink-700/80 px-4 py-3">
        {auditEntries.length === 0 ? (
          <EmptyState
            title="No steps yet"
            description="Run a pipeline to see parse, match, negotiate, and gate steps."
          />
        ) : (
          <ol className="space-y-3">
            {auditEntries.map((entry, i) => {
              const st = String(entry.step_type || 'deterministic')
              return (
                <li
                  key={`${entry.step_name}-${i}`}
                  className={`rounded-lg border border-ink-700/80 border-l-4 bg-ink-900/50 p-3 ${
                    typeStyles[st] || typeStyles.deterministic
                  }`}
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[0.65rem] font-medium uppercase tracking-wide">
                      {typeLabels[st] || st}
                    </span>
                    <span className="text-sm font-semibold text-ink-100">
                      {entry.step_name || 'step'}
                    </span>
                    {entry.duration_ms != null ? (
                      <span className="rounded-full border border-ink-700 px-2 py-0.5 font-mono text-[0.65rem] text-ink-500">
                        {Number(entry.duration_ms).toFixed(0)} ms
                      </span>
                    ) : null}
                  </div>
                  <dl className="grid gap-2 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="font-mono text-[0.65rem] uppercase text-ink-500">Input</dt>
                      <dd className="mt-0.5 text-ink-300">{entry.input_summary || '-'}</dd>
                    </div>
                    <div>
                      <dt className="font-mono text-[0.65rem] uppercase text-ink-500">Output</dt>
                      <dd className="mt-0.5 text-ink-300">{entry.output_summary || '-'}</dd>
                    </div>
                  </dl>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </details>
  )
}
