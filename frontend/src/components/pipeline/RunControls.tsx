import { Play } from 'lucide-react'
import { usePipeline } from '@/hooks/usePipeline'

export function RunControls() {
  const {
    samples,
    selectedSample,
    setSelectedSample,
    running,
    runPipeline,
    wsState,
  } = usePipeline()

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-paper-edge bg-paper p-3 shadow-panel">
      <label className="sr-only" htmlFor="sample-select">
        Sample invoice
      </label>
      <select
        id="sample-select"
        value={selectedSample}
        onChange={(e) => setSelectedSample(e.target.value)}
        disabled={running}
        className="min-w-[220px] flex-1 appearance-none rounded-lg border border-ink-700 bg-ink-950 bg-[length:12px] bg-[right_0.9rem_center] bg-no-repeat px-3 py-2.5 pr-9 text-sm text-ink-100 outline-none focus:border-teal-accent/50"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath fill='%236b7589' d='M1 1l5 5 5-5'/%3E%3C/svg%3E")`,
        }}
      >
        <option value="">Select a sample invoice…</option>
        {samples.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => void runPipeline()}
        disabled={running || wsState !== 'open' || !selectedSample}
        className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-br from-teal-muted to-teal-accent px-4 py-2.5 text-sm font-semibold text-ink-950 transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-45"
      >
        <Play className="h-4 w-4" fill="currentColor" />
        {running ? 'Running…' : 'Run Pipeline'}
      </button>
    </div>
  )
}
