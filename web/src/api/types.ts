export type ChannelStatus = 'disconnected' | 'connecting' | 'connected' | 'requires_qr' | 'failed'
export type ConversationStatus = 'new' | 'open' | 'closed'
export type MessageStatus = 'pending' | 'sent' | 'delivered' | 'read' | 'failed'
export type MessageType = 'text' | 'image' | 'document' | 'audio' | 'video' | 'sticker'
export type UserRole = 'admin' | 'agent'

export interface CurrentUser {
  id: string
  tenant_id: string
  email: string
  name: string
  role: UserRole
}

export interface TenantUser {
  id: string
  name: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface Channel {
  id: string
  name: string
  phone_number: string | null
  provider: 'evolution_go' | 'meta_cloud' | 'bsp'
  status: ChannelStatus
  provider_config: Record<string, unknown>
}

export interface Conversation {
  id: string
  status: ConversationStatus
  assigned_user_id: string | null
  contact_id: string
  contact_name: string | null
  contact_phone: string
  channel_id: string
  channel_status: ChannelStatus
  last_message_at: string | null
  last_message_body: string | null
  last_message_type: Message['message_type'] | null
  last_message_direction: Message['direction'] | null
  unread_count: number
}

export interface ContactDetail {
  id: string
  display_name: string
  name: string | null
  push_name: string | null
  business_name: string | null
  verified_name: string | null
  phone_number: string
  about: string | null
  profile_picture_url: string | null
  is_on_whatsapp: boolean | null
  profile_synced_at: string | null
  profile_sync_error: string | null
  first_interaction_at: string | null
  last_interaction_at: string | null
  conversation_count: number
  closed_conversation_count: number
}

export interface Message {
  id: string
  conversation_id: string
  direction: 'incoming' | 'outgoing'
  message_type: MessageType
  status: MessageStatus
  body: string | null
  reply_to_message_id: string | null
  reply_to_provider_message_id: string | null
  reply_to: {
    id: string
    direction: 'incoming' | 'outgoing'
    message_type: MessageType
    body: string | null
  } | null
  attachments: MessageAttachment[]
  provider_message_id: string | null
  error: string | null
  attempt_count: number
  last_attempt_at: string | null
  sent_at: string | null
  delivered_at: string | null
  read_at: string | null
  edited_at: string | null
  edit_content_unavailable: boolean
  created_at: string
}

export interface MessageAttachment {
  id: string
  file_name: string
  content_type: string
  size_bytes: number
  public_url: string
}

export interface QuickReply {
  id: string
  shortcut: string
  title: string
  content: string
}
