import { Inbox, Radio } from 'lucide-react'
import { Badge } from '@/components/common/Badge'
import { usePipeline } from '@/hooks/usePipeline'

export function Header() {
  const {
    wsLabel,
    wsState,
    inboxListening,
    emailsProcessed,
    lastSender,
    statusLine,
  } = usePipeline()

  return (
    <header className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink-100 sm:text-3xl">
          Agent Finance
        </h1>
        <p className="mt-1 max-w-xl text-sm text-ink-500">
          AP dispute pipeline - parse, match, negotiate, gate, and persist with a live audit trail.
        </p>
        <p
          className="mt-3 text-sm font-medium text-teal-accent"
          aria-live="polite"
        >
          {statusLine}
        </p>
      </div>

      <div className="flex shrink-0 flex-col items-stretch gap-2 sm:items-end">
        <Badge variant={wsState === 'open' ? 'live' : 'warn'}>
          <Radio className="h-3 w-3" />
          {wsLabel}
        </Badge>

        <div className="flex max-w-xs items-start gap-2.5 rounded-xl border border-gate-escalate/35 bg-gate-escalate/10 px-3 py-2.5 text-xs text-[#f5d67b]">
          <span className="mt-1.5 h-2 w-2 shrink-0 animate-pulseDot rounded-full bg-gate-escalate" />
          <div>
            <div className="flex items-center gap-1.5 font-medium text-ink-100">
              <Inbox className="h-3.5 w-3.5" />
              Inbox {inboxListening ? '- listening' : '- idle'}
            </div>
            <div className="mt-0.5 text-ink-300">
              Processed: <strong className="text-ink-100">{emailsProcessed}</strong>
              {lastSender ? ` · last from ${lastSender}` : null}
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
