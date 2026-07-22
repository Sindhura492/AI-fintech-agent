import type {
  AnomalyResolveResponse,
  EscalationResolveResponse,
  InboxStatus,
  MetricsSummary,
  ReviewsResponse,
  RunRequest,
  RunResponse,
  SampleOption,
} from '@/types/api'
import type { AuditEntry, VendorContext } from '@/types/pipeline'

async function parseError(res: Response): Promise<string> {
  try {
    const text = await res.text()
    return text || res.statusText
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await parseError(res))
  return res.json() as Promise<T>
}

async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json() as Promise<T>
}

export const FALLBACK_SAMPLES: SampleOption[] = [
  { id: 'po1001', label: 'PO-1001 - Clean match (Meridian)', po_id: 'PO-1001' },
  { id: 'po1002', label: 'PO-1002 - Small mismatch ~2% (Cascade)', po_id: 'PO-1002' },
  { id: 'po1003', label: 'PO-1003 - Large mismatch ~18% (Northwind)', po_id: 'PO-1003' },
]

export const SAMPLE_VENDORS: Record<string, string> = {
  po1001: 'Meridian Office Supply',
  po1002: 'Cascade Industrial Parts',
  po1003: 'Northwind Components',
}

export async function fetchSamples(): Promise<SampleOption[]> {
  try {
    const data = await getJson<SampleOption[]>('/samples')
    if (Array.isArray(data) && data.length > 0) return data
  } catch {
    /* fall through */
  }
  return FALLBACK_SAMPLES
}

export async function runPipeline(body: RunRequest): Promise<RunResponse> {
  return postJson<RunResponse>('/run', body)
}

export async function fetchMetrics(): Promise<MetricsSummary> {
  return getJson<MetricsSummary>('/metrics')
}

export async function fetchInboxStatus(): Promise<InboxStatus> {
  return getJson<InboxStatus>('/inbox/status')
}

export async function fetchInboxTrace(sessionId: string): Promise<AuditEntry[]> {
  return getJson<AuditEntry[]>(`/inbox/trace/${encodeURIComponent(sessionId)}`)
}

export async function fetchInboxLive(sessionId: string): Promise<Record<string, unknown>[]> {
  return getJson<Record<string, unknown>[]>(`/inbox/live/${encodeURIComponent(sessionId)}`)
}

export async function fetchReviews(sessionId: string): Promise<ReviewsResponse> {
  return getJson<ReviewsResponse>(`/reviews/${encodeURIComponent(sessionId)}`)
}

export async function fetchVendorGraph(vendorName: string): Promise<VendorContext> {
  return getJson<VendorContext>(`/vendor-graph/${encodeURIComponent(vendorName)}`)
}

export async function approveEscalation(sessionId: string): Promise<EscalationResolveResponse> {
  return postJson<EscalationResolveResponse>(`/approve/${encodeURIComponent(sessionId)}`)
}

export async function denyEscalation(sessionId: string): Promise<EscalationResolveResponse> {
  return postJson<EscalationResolveResponse>(`/deny/${encodeURIComponent(sessionId)}`)
}

export async function approveAnomaly(sessionId: string): Promise<AnomalyResolveResponse> {
  return postJson<AnomalyResolveResponse>(`/anomaly/approve/${encodeURIComponent(sessionId)}`)
}

export async function denyAnomaly(sessionId: string): Promise<AnomalyResolveResponse> {
  return postJson<AnomalyResolveResponse>(`/anomaly/deny/${encodeURIComponent(sessionId)}`)
}
