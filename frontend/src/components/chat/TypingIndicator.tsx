import type { Speaker } from '@/types/pipeline'

export function TypingIndicator({ speaker }: { speaker: Speaker }) {
  const isBuyer = speaker === 'buyer'
  return (
    <div
      className={`flex w-full animate-rise ${isBuyer ? 'justify-end' : 'justify-start'}`}
      aria-label={`${speaker} thinking`}
    >
      <div
        className={`flex items-center gap-1.5 rounded-full border px-3 py-2 ${
          isBuyer
            ? 'border-[rgba(45,212,168,0.35)] bg-[rgba(45,212,168,0.1)]'
            : 'border-[rgba(91,159,212,0.35)] bg-[rgba(91,159,212,0.1)]'
        }`}
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 rounded-full bg-ink-300"
            style={{ animation: `typing 1.2s ease-in-out ${i * 0.15}s infinite` }}
          />
        ))}
      </div>
    </div>
  )
}
