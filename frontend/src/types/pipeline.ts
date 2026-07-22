export type SampleId = 'po1001' | 'po1002' | 'po1003'

export type PipelineStage =
  | 'idle'
  | 'parse'
  | 'extract'
  | 'match'
  | 'validate'
  | 'negotiate'
  | 'gate'
  | 'persist'
  | 'done'
  | 'error'

export type GateAction = 'approve' | 'deny' | 'escalate' | null

export type Speaker = 'buyer' | 'supplier'

export type StepType = 'llm' | 'deterministic' | 'ml' | string

export interface AuditEntry {
  type?: 'audit'
  step_name?: string
  step_type?: StepType
  input_summary?: string
  output_summary?: string
  duration_ms?: number | null
  details?: Record<string, unknown>
  timestamp?: string
  session_id?: string
}

export interface AgentMessage {
  type: 'agent_message'
  speaker: Speaker | string
  text?: string
  amount?: number | null
  round_number?: number | null
  verified?: boolean
  session_id?: string
}

export interface AgentThinking {
  type: 'agent_thinking'
  speaker: Speaker | string
  round_number?: number | null
  session_id?: string
}

export interface SettlementBanner {
  type: 'settlement_banner'
  converged?: boolean
  amount?: number | null
  session_id?: string
}

export interface SettlementOutcomeRecent {
  final_amount?: number
  agreed_by_both?: boolean
}

export interface VendorContext {
  type?: 'vendor_context'
  vendor_name?: string
  invoice_count?: number
  dispute_count?: number
  avg_discrepancy?: number | null
  avg_invoice_amount?: number | null
  settlement_outcomes?: {
    agreed_count?: number
    not_agreed_count?: number
    avg_settlement_amount?: number | null
    recent?: SettlementOutcomeRecent[]
  }
  last_updated?: string | null
  source?: string
  available?: boolean
  session_id?: string
}

export type ReviewKind = 'escalation' | 'anomaly'

export interface ReviewItem {
  kind: ReviewKind
  session_id: string
  vendor_name?: string
  amount?: number | null
  status?: string
  action?: string
  resolved_action?: string
  reason?: string
  display_reason?: string
  rule_fired?: string
  payment_executed?: boolean
  anomaly_score?: number | null
  method?: string
  explanation?: string
  po_id?: string
}

export interface GateDecision {
  action: GateAction
  rule_fired?: string
  reason?: string
  label?: string
}

export interface ChatMessage {
  id: string
  speaker: Speaker
  text: string
  amount?: number | null
  round_number?: number | null
  verified?: boolean
}

export type WsConnectionState = 'connecting' | 'open' | 'closed' | 'error'

export type LiveEvent =
  | { type: 'subscribed'; session_id: string }
  | { type: 'error'; message?: string }
  | AgentThinking
  | AgentMessage
  | SettlementBanner
  | VendorContext
  | (ReviewItem & { type: string })
  | AuditEntry
  | Record<string, unknown>
