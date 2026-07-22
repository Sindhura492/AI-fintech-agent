import { NegotiationPanel } from '@/components/chat/NegotiationPanel'
import { OutcomeBanner } from '@/components/pipeline/OutcomeBanner'
import { RunControls } from '@/components/pipeline/RunControls'
import { StageRail } from '@/components/pipeline/StageRail'
import { StepTimeline } from '@/components/pipeline/StepTimeline'
import { VendorContextCard } from '@/components/pipeline/VendorContextCard'
import { WhatsHappening } from '@/components/pipeline/WhatsHappening'
import { ReviewQueue } from '@/components/reviews/ReviewQueue'

export function LivePage() {
  return (
    <div>
      <RunControls />
      <WhatsHappening />
      <StageRail />
      <VendorContextCard />
      <NegotiationPanel />
      <OutcomeBanner />
      <ReviewQueue />
      <StepTimeline />
    </div>
  )
}
