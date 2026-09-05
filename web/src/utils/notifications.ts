import type { Conversation, MessageType } from '../api/types'
import { isDesktopNotificationEnabled } from '../composables/useInterfacePreferences'

export type DesktopNotificationPermission = NotificationPermission | 'unsupported'
type RenotifyNotificationOptions = NotificationOptions & { renotify?: boolean }

const NOTIFICATION_CLAIMS_KEY = 'fluvius_desktop_notification_claims'
const CLAIM_TTL_MS = 10 * 60 * 1_000
const MAX_CLAIMS = 100

const messageTypeLabels: Record<MessageType, string> = {
  text: 'Nova mensagem',
  image: 'Foto',
  document: 'Documento',
  audio: 'Áudio',
  video: 'Vídeo',
  sticker: 'Figurinha',
  contact: 'Contato',
}

export function getDesktopNotificationPermission(): DesktopNotificationPermission {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission
}

export async function requestDesktopNotificationPermission(): Promise<DesktopNotificationPermission> {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.requestPermission()
}

function normalizePreview(value: string | null) {
  return value?.replace(/\s+/g, ' ').trim().slice(0, 160) || ''
}

function conversationPreview(conversation: Conversation) {
  const type = conversation.last_message_type || 'text'
  const body = normalizePreview(conversation.last_message_body)
  if (type === 'text') return body || messageTypeLabels.text
  return body ? `${messageTypeLabels[type]}: ${body}` : messageTypeLabels[type]
}

function claimMessageNotification(tenantId: string, messageId: string) {
  try {
    const now = Date.now()
    const claimId = `${tenantId}:${messageId}`
    const parsed = JSON.parse(localStorage.getItem(NOTIFICATION_CLAIMS_KEY) || '{}') as Record<
      string,
      number
    >
    const recentClaims = Object.entries(parsed)
      .filter(([, claimedAt]) => Number.isFinite(claimedAt) && now - claimedAt < CLAIM_TTL_MS)
      .sort(([, firstClaimedAt], [, secondClaimedAt]) => secondClaimedAt - firstClaimedAt)
      .slice(0, MAX_CLAIMS)

    if (recentClaims.some(([key]) => key === claimId)) return false
    localStorage.setItem(
      NOTIFICATION_CLAIMS_KEY,
      JSON.stringify(Object.fromEntries([[claimId, now], ...recentClaims].slice(0, MAX_CLAIMS))),
    )
    return true
  } catch {
    return true
  }
}

export function showConversationNotification(
  conversation: Conversation,
  tenantId: string,
  messageId: string,
  selectedConversationId: string | null,
) {
  if (
    !isDesktopNotificationEnabled() ||
    getDesktopNotificationPermission() !== 'granted' ||
    !claimMessageNotification(tenantId, messageId)
  ) {
    return false
  }

  if (
    document.visibilityState === 'visible' &&
    selectedConversationId === conversation.id
  ) {
    return false
  }

  try {
    const title = conversation.contact_name?.trim() || conversation.contact_phone
    const options: RenotifyNotificationOptions = {
      body: `${conversationPreview(conversation)}\n${conversation.channel_name}`,
      tag: `fluvius-chat:${tenantId}:${conversation.id}`,
      renotify: true,
      silent: true,
    }
    const notification = new Notification(title, options)
    notification.onclick = () => {
      notification.close()
      window.focus()
      const target = new URL('/app/conversations', window.location.origin)
      target.searchParams.set('conversation', conversation.id)
      target.searchParams.set('channel', conversation.channel_id)
      window.location.assign(target)
    }
    return true
  } catch {
    return false
  }
}

export function showTestConversationNotification() {
  if (getDesktopNotificationPermission() !== 'granted') return false
  try {
    const options: RenotifyNotificationOptions = {
      body: 'Esta é a prévia de uma nova mensagem.\nFluvius',
      tag: 'fluvius-chat:test',
      renotify: true,
      silent: true,
    }
    const notification = new Notification('Chat de teste', options)
    notification.onclick = () => {
      notification.close()
      window.focus()
    }
    return true
  } catch {
    return false
  }
}
