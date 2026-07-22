import { formatMoney } from '@/lib/format'
import type { ChatMessage } from '@/types/pipeline'
import { CheckCircle2 } from 'lucide-react'

export function ChatBubble({ message }: { message: ChatMessage }) {
  const isBuyer = message.speaker === 'buyer'
  return (
    <div
      className={`flex w-full animate-rise ${isBuyer ? 'justify-end' : 'justify-start'}`}
    >
      <div
        className={`max-w-[min(78%,420px)] rounded-[14px] border px-3.5 py-3 ${
          isBuyer
            ? 'rounded-br-md border-[rgba(45,212,168,0.4)] bg-[rgba(45,212,168,0.12)]'
            : 'rounded-bl-md border-[rgba(91,159,212,0.4)] bg-[rgba(91,159,212,0.12)]'
        }`}
      >
        <div className="mb-1.5 flex items-center justify-between gap-3">
          <span
            className={`text-xs font-semibold ${
              isBuyer ? 'text-teal-accent' : 'text-[var(--supplier)]'
            }`}
          >
            {isBuyer ? 'Buyer agent' : 'Supplier agent'}
          </span>
          <span className="font-mono text-[0.65rem] text-ink-500">
            round {message.round_number ?? '-'}
          </span>
        </div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-100">
          {message.text}
        </p>
        <div className="mt-2 font-mono text-sm font-medium text-ink-300">
          {formatMoney(message.amount)}
        </div>
        {message.verified ? (
          <div className="mt-1.5 flex items-center gap-1 text-xs text-teal-accent">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Verified against source data
          </div>
        ) : null}
      </div>
    </div>
  )
}
