import { MetricsOverview } from '@/components/monitoring/MetricsOverview'
import { RunsTable } from '@/components/monitoring/RunsTable'

export function MonitoringPage() {
  return (
    <div>
      <MetricsOverview />
      <RunsTable />
    </div>
  )
}
