import { usePipeline } from '@/hooks/usePipeline'
import { Panel } from '@/components/common/Panel'
import { Info } from 'lucide-react'

export function WhatsHappening() {
  const { statusLine, stage, gate, running, activeSession } = usePipeline()

  const detail =
    gate?.action === 'approve'
      ? 'Payment was allowed by the enforcement gate.'
      : gate?.action === 'deny'
        ? 'Payment blocked - settlement outside policy bounds.'
        : gate?.action === 'escalate'
          ? 'Needs a human - see the review queue below.'
          : running
            ? 'Watch the stage rail and negotiation chat update live.'
            : activeSession
              ? 'Last run is loaded. Pick a sample to run again, or wait for email.'
              : 'Select a sample above and click Run - or email a PDF to the inbox.'

  return (
    <Panel className="mb-4 border-teal-accent/20 bg-teal-soft/40">
      <div className="flex gap-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-teal-accent" aria-hidden />
        <div className="min-w-0">
          <div className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-500">
            What&apos;s happening
          </div>
          <p className="mt-1 text-sm font-medium text-ink-100">{statusLine}</p>
          <p className="mt-1 text-xs text-ink-400">
            Stage: <span className="font-mono text-ink-300">{stage}</span>
            {' · '}
            {detail}
          </p>
        </div>
      </div>
    </Panel>
  )
}
