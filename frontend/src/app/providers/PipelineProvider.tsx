import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  approveAnomaly,
  approveEscalation,
  denyAnomaly,
  denyEscalation,
  FALLBACK_SAMPLES,
  fetchInboxLive,
  fetchInboxStatus,
  fetchInboxTrace,
  fetchMetrics,
  fetchReviews,
  fetchSamples,
  fetchVendorGraph,
  runPipeline as apiRunPipeline,
  SAMPLE_VENDORS,
} from '@/lib/api'
import { formatSessionShort } from '@/lib/format'
import { notifyBrowser, requestNotifyPermission } from '@/lib/notify'
import { newSessionId, PipelineWebSocket } from '@/lib/ws'
import type { MetricsSummary, SampleOption } from '@/types/api'
import type {
  AuditEntry,
  ChatMessage,
  GateDecision,
  PipelineStage,
  ReviewItem,
  ReviewKind,
  SettlementBanner,
  Speaker,
  VendorContext,
  WsConnectionState,
} from '@/types/pipeline'

export type AppTab = 'live' | 'monitoring'

export interface PipelineContextValue {
  tab: AppTab
  setTab: (tab: AppTab) => void
  samples: SampleOption[]
  selectedSample: string
  setSelectedSample: (id: string) => void
  running: boolean
  statusLine: string
  stage: PipelineStage
  wsState: WsConnectionState
  wsLabel: string
  activeSession: string | null
  chatMessages: ChatMessage[]
  typingSpeaker: Speaker | null
  auditEntries: AuditEntry[]
  vendorContext: VendorContext | null
  vendorContextSource: 'preview' | 'live' | null
  settlement: SettlementBanner | null
  gate: GateDecision | null
  reviews: ReviewItem[]
  inboxListening: boolean
  emailsProcessed: number
  lastSender: string | null
  metrics: MetricsSummary | null
  metricsError: string | null
  runPipeline: () => Promise<void>
  resolveReview: (kind: ReviewKind, sessionId: string, action: 'approve' | 'deny') => Promise<void>
  resolvingKey: string | null
}

const PipelineContext = createContext<PipelineContextValue | null>(null)

const STAGE_ORDER: PipelineStage[] = [
  'parse',
  'extract',
  'match',
  'validate',
  'negotiate',
  'gate',
  'persist',
]

function stageFromStepName(stepName: string | undefined): PipelineStage | null {
  if (!stepName) return null
  const s = stepName.toLowerCase()

  if (s === 'pipeline_error' || s === 'client_error') return 'error'
  if (s === 'pipeline_complete') return 'done'

  if (
    s.includes('llamaparse') ||
    s === 'pipeline_start' ||
    s.includes('sandbox') ||
    s.includes('ingest')
  ) {
    return 'parse'
  }
  if (s.includes('extract')) return 'extract'
  if (s.includes('match') || s.includes('three_way')) return 'match'
  if (s.includes('validat') || s.includes('anomaly') || s.includes('isolation')) return 'validate'
  if (
    s.includes('negotiat') ||
    s.includes('supplier_agent') ||
    s.includes('buyer_agent') ||
    s.includes('cash_') ||
    s.includes('settlement') ||
    s.includes('bounds') ||
    s.includes('demo_negotiation') ||
    s.includes('compute_bounds') ||
    s.includes('verify_')
  ) {
    return 'negotiate'
  }
  if (
    s.includes('gate') ||
    s === 'enforce' ||
    s.includes('escalation') ||
    s.includes('human_decision')
  ) {
    return 'gate'
  }
  if (
    s.includes('persist') ||
    s.includes('knowledge_graph') ||
    s.includes('payment') ||
    s.includes('orchestrator')
  ) {
    return 'persist'
  }
  return null
}

function statusFromStepName(stepName: string | undefined, fallback: string): string {
  if (!stepName) return fallback
  const map: Record<string, string> = {
    pipeline_start: 'Starting pipeline…',
    llamaparse_document: 'Parsing invoice document…',
    extract_invoice: 'Extracting invoice fields…',
    match_to_po: 'Matching invoice to purchase order…',
    three_way_match: 'Running three-way match…',
    isolation_forest_anomaly: 'Checking for anomalies…',
    anomaly_review_queued: 'Anomaly flagged - waiting for human…',
    anomaly_hold: 'Paused - approve anomaly to continue…',
    anomaly_cleared: 'Anomaly cleared - resuming…',
    anomaly_blocked_pipeline: 'Anomaly denied - payment blocked',
    knowledge_graph_read: 'Loading vendor history…',
    compute_bounds: 'Computing negotiation bounds…',
    supplier_agent: 'Supplier agent proposing…',
    buyer_agent: 'Buyer agent responding…',
    cash_optimization_start: 'Evaluating early-pay discount…',
    cash_supplier_agent: 'Supplier discussing cash terms…',
    cash_buyer_agent: 'Buyer evaluating cash discount…',
    finalize_settlement: 'Settlement reached…',
    escalate_settlement: 'No convergence - escalating…',
    demo_negotiation: 'Running demo negotiation…',
    gate_decision: 'Applying payment gate rules…',
    enforce: 'Enforcing gate decision…',
    escalation_pending: 'Waiting for human approval…',
    human_decision: 'Recording human decision…',
    execute_payment: 'Executing payment…',
    knowledge_graph_write: 'Persisting vendor graph…',
    payment_executed: 'Payment recorded…',
    pipeline_complete: 'Pipeline complete',
    pipeline_error: 'Pipeline failed',
    client_error: 'Request failed',
  }
  if (map[stepName]) return map[stepName]
  if (stepName.includes('negotiat')) return 'Agents negotiating…'
  if (stepName.includes('bounds')) return 'Checking proposal bounds…'
  return `Processing: ${stepName.replace(/_/g, ' ')}…`
}

function advanceStage(current: PipelineStage, next: PipelineStage | null): PipelineStage {
  if (!next) return current
  if (next === 'done' || next === 'error' || next === 'idle') return next
  if (current === 'idle' || current === 'done' || current === 'error') return next
  const curIdx = STAGE_ORDER.indexOf(current)
  const nextIdx = STAGE_ORDER.indexOf(next)
  if (curIdx < 0) return next
  if (nextIdx < 0) return current
  return nextIdx >= curIdx ? next : current
}

function reviewKey(kind: ReviewKind, sessionId: string): string {
  return `${kind}:${sessionId}`
}

function normalizeReview(raw: Record<string, unknown>, fallbackKind?: ReviewKind): ReviewItem | null {
  const kindRaw = String(raw.kind || fallbackKind || '')
  const kind: ReviewKind =
    kindRaw === 'anomaly' || raw.type === 'anomaly_pending' || raw.type === 'anomaly_resolved'
      ? 'anomaly'
      : 'escalation'
  const sessionId = String(raw.session_id || '')
  if (!sessionId) return null
  return {
    kind,
    session_id: sessionId,
    vendor_name: raw.vendor_name != null ? String(raw.vendor_name) : undefined,
    amount: typeof raw.amount === 'number' ? raw.amount : raw.amount == null ? null : Number(raw.amount),
    status: raw.status != null ? String(raw.status) : undefined,
    action: raw.action != null ? String(raw.action) : undefined,
    resolved_action: raw.resolved_action != null ? String(raw.resolved_action) : undefined,
    reason: raw.reason != null ? String(raw.reason) : undefined,
    display_reason: raw.display_reason != null ? String(raw.display_reason) : undefined,
    rule_fired: raw.rule_fired != null ? String(raw.rule_fired) : undefined,
    payment_executed: Boolean(raw.payment_executed),
    anomaly_score:
      typeof raw.anomaly_score === 'number'
        ? raw.anomaly_score
        : raw.anomaly_score == null
          ? null
          : Number(raw.anomaly_score),
    method: raw.method != null ? String(raw.method) : undefined,
    explanation: raw.explanation != null ? String(raw.explanation) : undefined,
    po_id: raw.po_id != null ? String(raw.po_id) : undefined,
  }
}

function gateFromDetails(
  details: Record<string, unknown> | undefined,
  fallbackReason?: string,
): GateDecision | null {
  if (!details) return null
  const actionRaw = String(details.action || '').toLowerCase()
  let action: GateDecision['action'] = 'escalate'
  let label = 'ESCALATE'
  if (actionRaw === 'approve') {
    action = 'approve'
    label = 'APPROVE'
  } else if (actionRaw === 'deny') {
    action = 'deny'
    label = 'DENY'
  } else if (!actionRaw) {
    return null
  }
  return {
    action,
    rule_fired: details.rule_fired != null ? String(details.rule_fired) : undefined,
    reason: fallbackReason || (details.reason != null ? String(details.reason) : undefined),
    label,
  }
}

let msgCounter = 0
function nextMsgId(): string {
  msgCounter += 1
  return `msg-${msgCounter}`
}

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<AppTab>('live')
  const [samples, setSamples] = useState<SampleOption[]>(FALLBACK_SAMPLES)
  const [selectedSample, setSelectedSampleState] = useState('')
  const [running, setRunning] = useState(false)
  const [statusLine, setStatusLine] = useState('Ready - pick a sample invoice and run the pipeline.')
  const [stage, setStage] = useState<PipelineStage>('idle')
  const [wsState, setWsState] = useState<WsConnectionState>('connecting')
  const [activeSession, setActiveSession] = useState<string | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [typingSpeaker, setTypingSpeaker] = useState<Speaker | null>(null)
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([])
  const [vendorContext, setVendorContext] = useState<VendorContext | null>(null)
  const [vendorContextSource, setVendorContextSource] = useState<'preview' | 'live' | null>(
    null,
  )
  const vendorContextSourceRef = useRef<'preview' | 'live' | null>(null)
  useEffect(() => {
    vendorContextSourceRef.current = vendorContextSource
  }, [vendorContextSource])
  const [settlement, setSettlement] = useState<SettlementBanner | null>(null)
  const [gate, setGate] = useState<GateDecision | null>(null)
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [inboxListening, setInboxListening] = useState(false)
  const [emailsProcessed, setEmailsProcessed] = useState(0)
  const [lastSender, setLastSender] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [resolvingKey, setResolvingKey] = useState<string | null>(null)

  const activeSessionRef = useRef<string | null>(null)
  const runningRef = useRef(false)
  const lastInboxSessionRef = useRef<string | null>(null)
  const emailsProcessedRef = useRef(0)
  const inboxSeededRef = useRef(false)
  const attachedActiveRef = useRef<string | null>(null)
  const wsRef = useRef<PipelineWebSocket | null>(null)

  useEffect(() => {
    activeSessionRef.current = activeSession
  }, [activeSession])
  useEffect(() => {
    runningRef.current = running
  }, [running])

  const clearLiveUi = useCallback(() => {
    setChatMessages([])
    setTypingSpeaker(null)
    setAuditEntries([])
    setVendorContext(null)
    setVendorContextSource(null)
    setSettlement(null)
    setGate(null)
    setReviews([])
    setStage('idle')
  }, [])

  const upsertReview = useCallback((item: ReviewItem) => {
    setReviews((prev) => {
      const key = reviewKey(item.kind, item.session_id)
      const idx = prev.findIndex((r) => reviewKey(r.kind, r.session_id) === key)
      if (idx === -1) return [...prev, item]
      const next = [...prev]
      next[idx] = { ...next[idx], ...item }
      return next
    })
  }, [])

  const refreshMetrics = useCallback(async () => {
    try {
      const data = await fetchMetrics()
      setMetrics(data)
      setMetricsError(null)
    } catch (err) {
      setMetricsError(String(err))
    }
  }, [])

  const applyAudit = useCallback(
    (entry: AuditEntry) => {
      setAuditEntries((prev) => [...prev, entry])
      const nextStage = stageFromStepName(entry.step_name)
      if (nextStage) {
        setStage((cur) => advanceStage(cur, nextStage))
      }
      if (entry.step_name) {
        setStatusLine(statusFromStepName(entry.step_name, 'Processing…'))
      }

      if (entry.step_name === 'enforce' || entry.step_name === 'gate_decision') {
        const g = gateFromDetails(entry.details, entry.output_summary)
        if (g) setGate(g)
      }

      if (entry.step_name === 'escalation_pending') {
        upsertReview({
          kind: 'escalation',
          session_id: String(entry.details?.session_id || activeSessionRef.current || ''),
          vendor_name: entry.details?.vendor_name != null ? String(entry.details.vendor_name) : undefined,
          amount: typeof entry.details?.amount === 'number' ? entry.details.amount : null,
          reason: entry.details?.reason != null ? String(entry.details.reason) : undefined,
          rule_fired: entry.details?.rule_fired != null ? String(entry.details.rule_fired) : undefined,
          status: 'pending',
        })
      }
      if (entry.step_name === 'human_decision') {
        upsertReview({
          kind: 'escalation',
          session_id: String(entry.details?.session_id || activeSessionRef.current || ''),
          action: entry.details?.action != null ? String(entry.details.action) : undefined,
          status: entry.details?.status != null ? String(entry.details.status) : undefined,
          vendor_name: entry.details?.vendor_name != null ? String(entry.details.vendor_name) : undefined,
          amount: typeof entry.details?.amount === 'number' ? entry.details.amount : null,
          reason: entry.details?.reason != null ? String(entry.details.reason) : undefined,
          rule_fired: entry.details?.rule_fired != null ? String(entry.details.rule_fired) : undefined,
          payment_executed: Boolean(entry.details?.payment_executed),
        })
        const action = String(entry.details?.action || '').toLowerCase()
        if (action === 'approve' || action === 'deny') {
          setGate({
            action: action as 'approve' | 'deny',
            rule_fired: entry.details?.rule_fired != null ? String(entry.details.rule_fired) : action === 'approve' ? 'HUMAN_APPROVE' : 'HUMAN_DENY',
            reason: action === 'approve' ? 'human approval after escalation' : 'human denial',
            label: action === 'approve' ? 'APPROVE' : 'DENY',
          })
        }
      }
      if (entry.step_name === 'anomaly_review_queued') {
        upsertReview({
          kind: 'anomaly',
          session_id: String(entry.details?.session_id || activeSessionRef.current || ''),
          vendor_name: entry.details?.vendor_name != null ? String(entry.details.vendor_name) : undefined,
          amount: typeof entry.details?.amount === 'number' ? entry.details.amount : null,
          anomaly_score: typeof entry.details?.anomaly_score === 'number' ? entry.details.anomaly_score : null,
          method: entry.details?.method != null ? String(entry.details.method) : undefined,
          explanation:
            entry.details?.explanation != null
              ? String(entry.details.explanation)
              : entry.output_summary,
          status: 'pending_review',
        })
      }
      if (entry.step_name === 'anomaly_human_decision') {
        upsertReview({
          kind: 'anomaly',
          session_id: String(entry.details?.session_id || activeSessionRef.current || ''),
          action: entry.details?.action != null ? String(entry.details.action) : undefined,
          status: entry.details?.status != null ? String(entry.details.status) : undefined,
          vendor_name: entry.details?.vendor_name != null ? String(entry.details.vendor_name) : undefined,
          amount: typeof entry.details?.amount === 'number' ? entry.details.amount : null,
          anomaly_score: typeof entry.details?.anomaly_score === 'number' ? entry.details.anomaly_score : null,
        })
      }

      if (entry.step_name === 'execute_payment') {
        const amount = entry.details?.amount
        notifyBrowser(
          'Payment approved',
          `Payment executed${typeof amount === 'number' ? ` · $${amount.toFixed(2)}` : ''}`,
          'approve',
        )
      }
      if (entry.step_name === 'pipeline_complete' || entry.step_name === 'pipeline_error') {
        setRunning(false)
        setTypingSpeaker(null)
        setStatusLine(
          entry.step_name === 'pipeline_complete' ? 'Pipeline complete' : 'Pipeline failed',
        )
        void refreshMetrics()
      }
    },
    [refreshMetrics, upsertReview],
  )

  const handleEvent = useCallback(
    (data: Record<string, unknown>) => {
      const type = String(data.type || '')
      const sid = data.session_id != null ? String(data.session_id) : undefined
      const active = activeSessionRef.current

      if (type === 'ready' || type === 'subscribed') {
        setStatusLine((prev) =>
          runningRef.current ? prev : `Live · ${formatSessionShort(sid || activeSessionRef.current)}`,
        )
        return
      }
      if (type === 'inbox_session_started') {
        const next = String(data.session_id || '')
        if (!next) return
        attachedActiveRef.current = next
        lastInboxSessionRef.current = next
        clearLiveUi()
        setActiveSession(next)
        setRunning(true)
        setStage('parse')
        setStatusLine('Email invoice received - streaming live…')
        return
      }
      if (type === 'error') {
        setStatusLine(String(data.message || 'WebSocket error'))
        return
      }

      if (active && sid && sid !== active) return

      if (type === 'vendor_context') {
        setVendorContext(data as unknown as VendorContext)
        setVendorContextSource('live')
        return
      }
      if (type === 'agent_thinking') {
        const speaker = data.speaker === 'buyer' ? 'buyer' : 'supplier'
        setTypingSpeaker(speaker)
        setStatusLine(
          speaker === 'buyer' ? 'Buyer agent thinking…' : 'Supplier agent thinking…',
        )
        setStage((cur) => advanceStage(cur, 'negotiate'))
        return
      }
      if (type === 'agent_message') {
        const speaker: Speaker = data.speaker === 'buyer' ? 'buyer' : 'supplier'
        setTypingSpeaker((t) => (t === speaker ? null : t))
        setChatMessages((prev) => [
          ...prev,
          {
            id: nextMsgId(),
            speaker,
            text: String(data.text || ''),
            amount: typeof data.amount === 'number' ? data.amount : null,
            round_number: typeof data.round_number === 'number' ? data.round_number : null,
            verified: Boolean(data.verified),
          },
        ])
        setStage((cur) => advanceStage(cur, 'negotiate'))
        setStatusLine(
          speaker === 'buyer'
            ? 'Buyer agent responded'
            : 'Supplier agent proposed',
        )
        return
      }
      if (type === 'settlement_banner') {
        setTypingSpeaker(null)
        setSettlement(data as unknown as SettlementBanner)
        setStatusLine(
          data.converged ? 'Settlement reached' : 'No convergence - escalating',
        )
        return
      }
      if (type === 'escalation_pending') {
        const item = normalizeReview(data, 'escalation')
        if (item) upsertReview({ ...item, status: item.status || 'pending' })
        setStage((cur) => advanceStage(cur, 'gate'))
        notifyBrowser(
          'Action needed: Invoice requires approval',
          `${item?.vendor_name || 'Vendor'} · ${item?.display_reason || item?.reason || 'escalated'}`,
          'escalate',
        )
        return
      }
      if (type === 'escalation_resolved') {
        const item = normalizeReview(data, 'escalation')
        if (item) upsertReview(item)
        return
      }
      if (type === 'anomaly_pending') {
        const item = normalizeReview(data, 'anomaly')
        if (item) upsertReview({ ...item, status: item.status || 'pending_review' })
        setStatusLine('Anomaly flagged - approve to continue…')
        notifyBrowser(
          'Anomaly flagged',
          `${item?.vendor_name || 'Vendor'} - review needed before pipeline continues`,
          'anomaly',
        )
        return
      }
      if (type === 'anomaly_hold') {
        const item = normalizeReview(data, 'anomaly')
        if (item) upsertReview({ ...item, status: item.status || 'pending_review' })
        setStatusLine('Paused - approve anomaly to continue…')
        notifyBrowser(
          'Anomaly flagged',
          `${item?.vendor_name || 'Vendor'} - pipeline paused`,
          'anomaly',
        )
        return
      }
      if (type === 'anomaly_resolved') {
        const item = normalizeReview(data, 'anomaly')
        if (item) upsertReview(item)
        const action = String(data.action || '').toLowerCase()
        setStatusLine(
          action === 'approve'
            ? 'Anomaly cleared - resuming…'
            : 'Anomaly denied - payment blocked',
        )
        return
      }
      if (type === 'audit' || data.step_name) {
        if (
          active &&
          data.details &&
          typeof data.details === 'object' &&
          data.details !== null &&
          'session_id' in (data.details as object) &&
          String((data.details as Record<string, unknown>).session_id) !== active
        ) {
          return
        }
        applyAudit({ ...data, type: 'audit' } as AuditEntry)
      }
    },
    [applyAudit, clearLiveUi, upsertReview],
  )

  const setSelectedSample = useCallback((id: string) => {
    setSelectedSampleState(id)
    if (!id) {
      // Clear sample preview; keep email context.
      if (vendorContextSourceRef.current === 'preview') {
        setVendorContext(null)
        setVendorContextSource(null)
      }
      return
    }
    // Load Neo4j context for selected sample.
    const vendor = SAMPLE_VENDORS[id]
    if (!vendor) return
    void fetchVendorGraph(vendor)
      .then((ctx) => {
        setVendorContext(ctx)
        setVendorContextSource('preview')
      })
      .catch(() => {
        /* optional */
      })
  }, [])

  const prefetchVendor = useCallback(async (sampleId: string) => {
    if (!sampleId) return
    if (vendorContextSourceRef.current === 'live') return
    const vendor = SAMPLE_VENDORS[sampleId]
    if (!vendor) return
    try {
      const ctx = await fetchVendorGraph(vendor)
      if (vendorContextSourceRef.current === 'live') return
      setVendorContext(ctx)
      setVendorContextSource('preview')
    } catch {
      /* optional */
    }
  }, [])

  const beginInboxSession = useCallback(
    async (sessionId: string, catchUp: boolean) => {
      attachedActiveRef.current = sessionId
      lastInboxSessionRef.current = sessionId
      clearLiveUi()
      setActiveSession(sessionId)
      setRunning(true)
      setStage('parse')
      setStatusLine(
        catchUp
          ? `Inbox session · ${formatSessionShort(sessionId)}`
          : 'Email invoice received - streaming live…',
      )
      if (!catchUp) return
      try {
        const [trace, live, reviewsPayload] = await Promise.all([
          fetchInboxTrace(sessionId),
          fetchInboxLive(sessionId),
          fetchReviews(sessionId).catch(() => ({ session_id: sessionId, items: [] })),
        ])
        for (const entry of trace) {
          applyAudit({ ...entry, type: 'audit' })
        }
        let sawVendorLive = false
        for (const ev of live) {
          if ((ev as { type?: string }).type === 'vendor_context') {
            sawVendorLive = true
          }
          handleEvent(ev)
        }
        if (!sawVendorLive) {
          const vendorFromReview = (reviewsPayload.items || [])
            .map((i) => (i as { vendor_name?: string }).vendor_name)
            .find((v) => typeof v === 'string' && v.trim())
          if (vendorFromReview) {
            try {
              const ctx = await fetchVendorGraph(vendorFromReview)
              setVendorContext(ctx)
              setVendorContextSource('live')
            } catch {
              /* optional */
            }
          }
        }
        for (const item of reviewsPayload.items || []) {
          const normalized = normalizeReview(item as Record<string, unknown>)
          if (normalized) upsertReview(normalized)
        }
      } catch {
        setStatusLine('Failed to load inbox session')
      }
    },
    [applyAudit, clearLiveUi, handleEvent, upsertReview],
  )

  useEffect(() => {
    void fetchSamples().then((list) => {
      setSamples(list)
    })
    requestNotifyPermission()
  }, [])

  useEffect(() => {
    const client = new PipelineWebSocket(handleEvent, setWsState)
    wsRef.current = client
    client.connect()
    return () => {
      client.close()
      wsRef.current = null
    }
  }, [handleEvent])

  useEffect(() => {
    void prefetchVendor(selectedSample)
  }, [selectedSample, prefetchVendor])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const data = await fetchInboxStatus()
        if (cancelled) return
        setInboxListening(Boolean(data.listening))
        setEmailsProcessed(Number(data.emails_processed || 0))
        setLastSender(data.last_sender ?? null)
        const n = Number(data.emails_processed || 0)
        const activeId = data.active_session_id || null

        // First poll after refresh: remember ids but do NOT reload old UI state.
        if (!inboxSeededRef.current) {
          inboxSeededRef.current = true
          lastInboxSessionRef.current = data.last_session_id
          emailsProcessedRef.current = n
          if (activeId) {
            attachedActiveRef.current = activeId
            await beginInboxSession(activeId, true)
          }
          return
        }

        // New email mid-flight (backup if WS announce was missed).
        if (activeId && activeId !== attachedActiveRef.current && !runningRef.current) {
          await beginInboxSession(activeId, true)
        } else if (activeId && activeId !== attachedActiveRef.current && runningRef.current) {
          attachedActiveRef.current = activeId
        }

        emailsProcessedRef.current = n
      } catch {
        /* ignore */
      }
    }
    void poll()
    const id = setInterval(poll, 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [beginInboxSession])

  useEffect(() => {
    void refreshMetrics()
    const id = setInterval(() => {
      void refreshMetrics()
    }, 5000)
    return () => clearInterval(id)
  }, [refreshMetrics])

  const runPipeline = useCallback(async () => {
    if (!selectedSample) {
      setStatusLine('Pick a sample invoice from the dropdown first')
      return
    }
    if (!wsRef.current?.ready) {
      setStatusLine('WebSocket not ready - wait for connection')
      return
    }
    clearLiveUi()
    setRunning(true)
    setStage('parse')
    setStatusLine('Starting pipeline…')
    void prefetchVendor(selectedSample)

    const sessionId = newSessionId()
    setActiveSession(sessionId)
    // Stay on subscribe-all so later email sessions still stream.
    wsRef.current.subscribeAll()

    try {
      await apiRunPipeline({ sample_id: selectedSample, session_id: sessionId })
      setStatusLine('Pipeline running - streaming live events…')
    } catch (err) {
      setRunning(false)
      setStage('error')
      setStatusLine(`Run failed: ${String(err)}`)
      applyAudit({
        type: 'audit',
        step_name: 'client_error',
        step_type: 'deterministic',
        input_summary: 'POST /run',
        output_summary: String(err),
        details: {},
      })
    }
  }, [applyAudit, clearLiveUi, prefetchVendor, selectedSample])

  const resolveReview = useCallback(
    async (kind: ReviewKind, sessionId: string, action: 'approve' | 'deny') => {
      const key = reviewKey(kind, sessionId)
      setResolvingKey(key)
      try {
        if (kind === 'anomaly') {
          const data =
            action === 'approve'
              ? await approveAnomaly(sessionId)
              : await denyAnomaly(sessionId)
          upsertReview({ ...data, kind: 'anomaly', session_id: sessionId })
        } else {
          const data =
            action === 'approve'
              ? await approveEscalation(sessionId)
              : await denyEscalation(sessionId)
          upsertReview({ ...data, kind: 'escalation', session_id: sessionId })
          setGate({
            action,
            rule_fired: action === 'approve' ? 'HUMAN_APPROVE' : 'HUMAN_DENY',
            reason:
              action === 'approve'
                ? 'human approval after escalation'
                : 'human denial',
            label: action === 'approve' ? 'APPROVE' : 'DENY',
          })
        }
      } finally {
        setResolvingKey(null)
      }
    },
    [upsertReview],
  )

  const wsLabel = useMemo(() => {
    if (wsState === 'open' && activeSession) {
      return `Live · ${formatSessionShort(activeSession)}`
    }
    if (wsState === 'open') return 'WS connected'
    if (wsState === 'connecting') return 'Connecting…'
    if (wsState === 'error') return 'WS error'
    return 'Disconnected - retrying…'
  }, [wsState, activeSession])

  const value: PipelineContextValue = {
    tab,
    setTab,
    samples,
    selectedSample,
    setSelectedSample,
    running,
    statusLine,
    stage,
    wsState,
    wsLabel,
    activeSession,
    chatMessages,
    typingSpeaker,
    auditEntries,
    vendorContext,
    vendorContextSource,
    settlement,
    gate,
    reviews,
    inboxListening,
    emailsProcessed,
    lastSender,
    metrics,
    metricsError,
    runPipeline,
    resolveReview,
    resolvingKey,
  }

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>
}

export function usePipelineContext(): PipelineContextValue {
  const ctx = useContext(PipelineContext)
  if (!ctx) throw new Error('usePipeline must be used within PipelineProvider')
  return ctx
}
