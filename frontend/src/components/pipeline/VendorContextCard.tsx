import { Network } from 'lucide-react'
import { Panel } from '@/components/common/Panel'
import { usePipeline } from '@/hooks/usePipeline'
import { formatMoney } from '@/lib/format'

export function VendorContextCard() {
  const { vendorContext, vendorContextSource } = usePipeline()
  if (!vendorContext?.vendor_name) return null

  const outcomes = vendorContext.settlement_outcomes || {}
  const recent =
    (outcomes.recent || [])
      .map(
        (r) =>
          `${formatMoney(r.final_amount)}${r.agreed_by_both ? ' agreed' : ' no-deal'}`,
      )
      .join(', ') || '-'

  const rows = [
    { label: 'Vendor', value: vendorContext.vendor_name },
    { label: 'Past invoices', value: String(vendorContext.invoice_count ?? 0) },
    { label: 'Past disputes', value: String(vendorContext.dispute_count ?? 0) },
    { label: 'Avg discrepancy', value: formatMoney(vendorContext.avg_discrepancy) },
    {
      label: 'Settlements agreed / not',
      value: `${outcomes.agreed_count ?? 0} / ${outcomes.not_agreed_count ?? 0}`,
    },
    {
      label: 'Avg settlement',
      value: formatMoney(outcomes.avg_settlement_amount),
    },
    { label: 'Recent outcomes', value: recent },
  ]

  const fromEmail = vendorContextSource === 'live'
  const title = fromEmail
    ? 'Vendor context (this email / run)'
    : 'Vendor context (sample preview)'

  return (
    <Panel
      className="mb-4"
      title={title}
      action={<Network className="h-4 w-4 text-ink-500" />}
    >
      <p className="mb-3 text-xs text-ink-400">
        {fromEmail
          ? 'From the invoice that just ran (email or Live Pipeline) - Neo4j history the agents used.'
          : 'Shown because you selected this sample in the dropdown.'}
      </p>
      <dl className="grid gap-3 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label}>
            <dt className="font-mono text-[0.65rem] uppercase tracking-wide text-ink-500">
              {row.label}
            </dt>
            <dd className="mt-0.5 text-sm text-ink-100">{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 font-mono text-[0.7rem] text-ink-500">
        source={vendorContext.source || 'graph'} · mode={vendorContextSource || '-'}
      </p>
    </Panel>
  )
}
