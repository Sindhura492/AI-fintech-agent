import { MessagesSquare } from 'lucide-react'
import { ChatBubble } from '@/components/chat/ChatBubble'
import { TypingIndicator } from '@/components/chat/TypingIndicator'
import { EmptyState } from '@/components/common/EmptyState'
import { Panel } from '@/components/common/Panel'
import { usePipeline } from '@/hooks/usePipeline'

export function NegotiationPanel() {
  const { chatMessages, typingSpeaker } = usePipeline()

  return (
    <Panel className="mb-4" title="Buyer ↔ Supplier negotiation">
      <div className="flex min-h-[200px] flex-col gap-3.5">
        {chatMessages.length === 0 && !typingSpeaker ? (
          <EmptyState
            icon={MessagesSquare}
            title="Waiting for agent messages"
            description="Run a pipeline to watch the supplier and buyer negotiate live."
          />
        ) : (
          <>
            {chatMessages.map((m) => (
              <ChatBubble key={m.id} message={m} />
            ))}
            {typingSpeaker ? <TypingIndicator speaker={typingSpeaker} /> : null}
          </>
        )}
      </div>
    </Panel>
  )
}
