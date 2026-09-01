import { readonly, ref } from 'vue'

const MESSAGE_SOUND_KEY = 'fluvius_message_sound'
const messageSoundEnabled = ref(true)
let initialized = false

export function initializeInterfacePreferences() {
  if (initialized) return
  messageSoundEnabled.value = localStorage.getItem(MESSAGE_SOUND_KEY) !== 'off'
  initialized = true
}

export function isMessageSoundEnabled() {
  initializeInterfacePreferences()
  return messageSoundEnabled.value
}

export function useInterfacePreferences() {
  initializeInterfacePreferences()

  function setMessageSoundEnabled(enabled: boolean) {
    messageSoundEnabled.value = enabled
    localStorage.setItem(MESSAGE_SOUND_KEY, enabled ? 'on' : 'off')
  }

  return {
    messageSoundEnabled: readonly(messageSoundEnabled),
    setMessageSoundEnabled,
  }
}
