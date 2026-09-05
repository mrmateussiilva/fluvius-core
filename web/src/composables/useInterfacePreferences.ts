import { readonly, ref } from 'vue'

const MESSAGE_SOUND_KEY = 'fluvius_message_sound'
const DESKTOP_NOTIFICATIONS_KEY = 'fluvius_desktop_notifications'
const messageSoundEnabled = ref(true)
const desktopNotificationsEnabled = ref(false)
let initialized = false

export function initializeInterfacePreferences() {
  if (initialized) return
  messageSoundEnabled.value = localStorage.getItem(MESSAGE_SOUND_KEY) !== 'off'
  desktopNotificationsEnabled.value =
    typeof Notification !== 'undefined' &&
    Notification.permission === 'granted' &&
    localStorage.getItem(DESKTOP_NOTIFICATIONS_KEY) !== 'off'
  initialized = true
}

export function isMessageSoundEnabled() {
  initializeInterfacePreferences()
  return messageSoundEnabled.value
}

export function isDesktopNotificationEnabled() {
  initializeInterfacePreferences()
  return desktopNotificationsEnabled.value
}

export function useInterfacePreferences() {
  initializeInterfacePreferences()

  function setMessageSoundEnabled(enabled: boolean) {
    messageSoundEnabled.value = enabled
    localStorage.setItem(MESSAGE_SOUND_KEY, enabled ? 'on' : 'off')
  }

  function setDesktopNotificationsEnabled(enabled: boolean) {
    desktopNotificationsEnabled.value = enabled
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, enabled ? 'on' : 'off')
  }

  return {
    desktopNotificationsEnabled: readonly(desktopNotificationsEnabled),
    messageSoundEnabled: readonly(messageSoundEnabled),
    setDesktopNotificationsEnabled,
    setMessageSoundEnabled,
  }
}
