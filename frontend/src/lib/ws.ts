export type WsMessageHandler = (data: Record<string, unknown>) => void
export type WsStatusHandler = (status: 'connecting' | 'open' | 'closed' | 'error') => void

export class PipelineWebSocket {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false
  private onMessage: WsMessageHandler
  private onStatus: WsStatusHandler

  constructor(onMessage: WsMessageHandler, onStatus: WsStatusHandler) {
    this.onMessage = onMessage
    this.onStatus = onStatus
  }

  connect(): void {
    this.intentionalClose = false
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    this.onStatus('connecting')
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws`)
    this.ws = ws

    ws.onopen = () => this.onStatus('open')
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(String(event.data)) as Record<string, unknown>
        this.onMessage(data)
      } catch {
        /* ignore malformed */
      }
    }
    ws.onerror = () => {
      this.onStatus('error')
      ws.close()
    }
    ws.onclose = () => {
      this.onStatus('closed')
      this.ws = null
      if (!this.intentionalClose) {
        this.reconnectTimer = setTimeout(() => this.connect(), 1500)
      }
    }
  }

  subscribe(sessionId: string): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify({ action: 'subscribe', session_id: sessionId }))
    return true
  }

  /** Receive events for every session (needed for live email ingest). */
  subscribeAll(): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify({ action: 'subscribe_all' }))
    return true
  }

  get ready(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN
  }

  close(): void {
    this.intentionalClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }
}

export function newSessionId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `sess-${Math.random().toString(16).slice(2)}${Date.now().toString(16)}`
}
