import { usePipeline } from '@/hooks/usePipeline'
import type { PipelineStage } from '@/types/pipeline'

const STAGES: { id: PipelineStage; label: string }[] = [
  { id: 'parse', label: 'Parse' },
  { id: 'extract', label: 'Extract' },
  { id: 'match', label: 'Match' },
  { id: 'validate', label: 'Validate' },
  { id: 'negotiate', label: 'Negotiate / Cash' },
  { id: 'gate', label: 'Gate' },
  { id: 'persist', label: 'Persist' },
]

function stageIndex(stage: PipelineStage): number {
  if (stage === 'done') return STAGES.length
  if (stage === 'idle' || stage === 'error') return -1
  return STAGES.findIndex((s) => s.id === stage)
}

export function StageRail() {
  const { stage } = usePipeline()
  const current = stageIndex(stage)
  const done = stage === 'done'
  const errored = stage === 'error'

  return (
    <nav
      aria-label="Pipeline stages"
      className="mb-4 overflow-x-auto rounded-xl border border-paper-edge bg-paper/80 px-2 py-3 shadow-panel"
    >
      <ol className="flex min-w-[640px] items-center gap-1 sm:min-w-0 sm:justify-between">
        {STAGES.map((s, i) => {
          const active = !done && !errored && i === current
          const completed = done || i < current
          return (
            <li key={s.id} className="flex flex-1 items-center gap-1">
              <div
                className={`flex w-full flex-col items-center gap-1 rounded-lg px-1 py-1 text-center transition ${
                  active ? 'bg-teal-soft' : ''
                }`}
              >
                <span
                  className={`flex h-2.5 w-2.5 rounded-full ${
                    errored && i === Math.max(current, 0)
                      ? 'bg-gate-deny'
                      : active
                        ? 'bg-teal-accent ring-4 ring-teal-soft'
                        : completed
                          ? 'bg-teal-muted'
                          : 'bg-ink-700'
                  }`}
                />
                <span
                  className={`text-[0.65rem] font-semibold leading-tight sm:text-[0.7rem] ${
                    active
                      ? 'text-teal-accent'
                      : completed
                        ? 'text-ink-300'
                        : 'text-ink-500'
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {i < STAGES.length - 1 ? (
                <div
                  className={`hidden h-px flex-1 sm:block ${
                    completed || done ? 'bg-teal-muted/50' : 'bg-ink-700'
                  }`}
                />
              ) : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
