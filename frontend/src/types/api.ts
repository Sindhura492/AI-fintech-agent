import type { SampleId } from './pipeline'

export interface SampleOption {
  id: SampleId | string
  label: string
  po_id?: string
  file?: string
}

export interface RunRequest {
  sample_id: string
  session_id?: string
}

export interface RunResponse {
  session_id: string
  po_id: string
  file_path: string
  sample_id: string
}

export interface InboxStatus {
  listening: boolean
  emails_processed: number
  last_session_id: string | null
  last_sender: string | null
  active_session_id?: string | null
}

export interface ReviewsResponse {
  session_id: string
  items: Array<Record<string, unknown>>
}

export interface EscalationResolveResponse {
  session_id: string
  status: string
  action: string
  vendor_name: string
  amount: number | null
  reason: string
  payment_executed: boolean
}

export interface AnomalyResolveResponse {
  session_id: string
  status: string
  action: string
  vendor_name: string
  amount: number
  anomaly_score: number
  explanation: string
}

export interface MetricsRun {
  session_id?: string
  timestamp?: string
  outcome?: string
  vendor?: string
  amount?: number | null
  success?: boolean
  anomaly_flagged?: boolean
  payment_executed?: boolean
}

export interface MetricsHealth {
  session_id?: string
  outcome?: string
  success?: boolean
}

export interface MetricsSummary {
  total_runs?: number
  runs_by_outcome?: {
    approved?: number
    denied?: number
    escalated?: number
    failed?: number
  }
  step_counts_by_type?: {
    llm?: number
    deterministic?: number
    ml?: number
  }
  avg_latency_per_step_type_ms?: {
    llm?: number | null
    deterministic?: number | null
    ml?: number | null
  }
  total_llm_calls?: number
  escalation_rate?: number
  anomaly_flag_rate?: number
  anomaly_flags?: number
  updated_at?: string | null
  recent_runs?: MetricsRun[]
  rate_series?: {
    labels?: string[]
    escalation_rate?: number[]
    anomaly_flag_rate?: number[]
  }
  health?: MetricsHealth[]
  db_path?: string
  metrics_log_count?: number
}
