import { AppShell } from '@/components/layout/AppShell'
import { usePipeline } from '@/hooks/usePipeline'
import { LivePage } from '@/pages/LivePage'
import { MonitoringPage } from '@/pages/MonitoringPage'

export default function App() {
  const { tab } = usePipeline()
  return <AppShell>{tab === 'live' ? <LivePage /> : <MonitoringPage />}</AppShell>
}
