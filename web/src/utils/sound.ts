import { isMessageSoundEnabled } from '../composables/useInterfacePreferences'

let audioCtx: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null
  if (!audioCtx) {
    const AudioContextClass =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext
    if (AudioContextClass) {
      audioCtx = new AudioContextClass()
    }
  }
  if (audioCtx && audioCtx.state === 'suspended') {
    void audioCtx.resume()
  }
  return audioCtx
}

export function playIncomingMessageSound(force = false): void {
  try {
    if (!force && !isMessageSoundEnabled()) return
    const ctx = getAudioContext()
    if (!ctx) return

    const now = ctx.currentTime

    // Tone 1: D5 (587.33 Hz)
    const osc1 = ctx.createOscillator()
    const gain1 = ctx.createGain()
    osc1.type = 'sine'
    osc1.frequency.setValueAtTime(587.33, now)
    gain1.gain.setValueAtTime(0.08, now)
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.12)
    osc1.connect(gain1)
    gain1.connect(ctx.destination)
    osc1.start(now)
    osc1.stop(now + 0.12)

    // Tone 2: A5 (880.00 Hz)
    const osc2 = ctx.createOscillator()
    const gain2 = ctx.createGain()
    osc2.type = 'sine'
    osc2.frequency.setValueAtTime(880, now + 0.07)
    gain2.gain.setValueAtTime(0.09, now + 0.07)
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.25)
    osc2.connect(gain2)
    gain2.connect(ctx.destination)
    osc2.start(now + 0.07)
    osc2.stop(now + 0.25)
  } catch {
    // Silently ignore browser autoplay restrictions
  }
}
