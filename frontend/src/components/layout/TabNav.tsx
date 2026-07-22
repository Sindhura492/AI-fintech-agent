import { Activity, Zap } from 'lucide-react'
import { usePipeline } from '@/hooks/usePipeline'
import type { AppTab } from '@/app/providers/PipelineProvider'

const tabs: { id: AppTab; label: string; icon: typeof Zap }[] = [
  { id: 'live', label: 'Live Pipeline', icon: Zap },
  { id: 'monitoring', label: 'Monitoring', icon: Activity },
]

export function TabNav() {
  const { tab, setTab } = usePipeline()

  return (
    <div className="mb-4 flex gap-1 rounded-xl border border-ink-700 bg-ink-900/80 p-1" role="tablist">
      {tabs.map(({ id, label, icon: Icon }) => {
        const active = tab === id
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => setTab(id)}
            className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-semibold transition ${
              active
                ? 'bg-ink-800 text-ink-100 shadow-sm'
                : 'text-ink-500 hover:text-ink-300'
            }`}
          >
            <Icon className="h-4 w-4" strokeWidth={2} />
            {label}
          </button>
        )
      })}
    </div>
  )
}
