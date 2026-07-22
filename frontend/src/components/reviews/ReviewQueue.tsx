import { ReviewCard } from '@/components/reviews/ReviewCard'
import { Panel } from '@/components/common/Panel'
import { usePipeline } from '@/hooks/usePipeline'

export function ReviewQueue() {
  const { reviews, resolveReview, resolvingKey } = usePipeline()
  if (reviews.length === 0) return null

  return (
    <Panel className="mb-4" title="Human review queue">
      <div className="space-y-3">
        {reviews.map((item) => {
          const key = `${item.kind}:${item.session_id}`
          return (
            <ReviewCard
              key={key}
              item={item}
              resolving={resolvingKey === key}
              onResolve={(kind, sessionId, action) => {
                void resolveReview(kind, sessionId, action)
              }}
            />
          )
        })}
      </div>
    </Panel>
  )
}
