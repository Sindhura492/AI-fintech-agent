/** Browser toast + short beep (backup when OS notifications are quiet). */

export function requestNotifyPermission(): void {
  if (typeof window === 'undefined' || !('Notification' in window)) return
  if (Notification.permission === 'default') {
    void Notification.requestPermission()
  }
}

function beep(freq = 880, ms = 180): void {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ctx = new Ctx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.value = freq
    gain.gain.value = 0.08
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.start()
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + ms / 1000)
    osc.stop(ctx.currentTime + ms / 1000)
    setTimeout(() => void ctx.close(), ms + 50)
  } catch {
    /* ignore */
  }
}

export function notifyBrowser(
  title: string,
  body: string,
  kind: 'escalate' | 'approve' | 'anomaly' = 'escalate',
): void {
  requestNotifyPermission()
  if (kind === 'escalate') beep(520, 220)
  else if (kind === 'anomaly') beep(660, 160)
  else beep(990, 140)

  if (typeof window === 'undefined' || !('Notification' in window)) return
  if (Notification.permission !== 'granted') return
  try {
    new Notification(title, {
      body: body.slice(0, 180),
      silent: false,
    })
  } catch {
    /* ignore */
  }
}
