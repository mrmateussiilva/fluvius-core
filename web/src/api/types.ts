export type ChannelStatus = 'disconnected' | 'connecting' | 'connected' | 'requires_qr' | 'failed'
export type ConversationStatus = 'new' | 'open' | 'closed'
export type MessageStatus = 'pending' | 'sent' | 'delivered' | 'read' | 'failed'
export type MessageType = 'text' | 'image' | 'document' | 'audio' | 'video' | 'sticker' | 'contact'
export type UserRole = 'admin' | 'agent'
export type SyncType = 'contacts' | 'messages' | 'all'
export type SyncStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed'
export type OperationalStatus = 'healthy' | 'attention' | 'critical'

export interface CurrentUser {
  id: string
  tenant_id: string
  tenant_name: string
  tenant_slug: string
  email: string
  name: string
  role: UserRole
  is_platform_admin: boolean
}

export interface AvailableTenant {
  id: string
  name: string
  slug: string
  role: UserRole
}

export interface PlatformTenant {
  id: string
  name: string
  slug: string
  is_active: boolean
  user_count: number
  active_user_count: number
  channel_count: number
  connected_channel_count: number
  created_at: string
}

export interface PlatformTenantMember {
  id: string
  name: string
  email: string
  role: UserRole
  is_active: boolean
  is_platform_admin: boolean
}

export interface PlatformTenantChannel {
  id: string
  name: string
  phone_number: string | null
  provider: Channel['provider']
  status: ChannelStatus
}

export interface PlatformTenantDetail extends PlatformTenant {
  users: PlatformTenantMember[]
  channels: PlatformTenantChannel[]
}

export interface TenantUser {
  id: string
  name: string
  email: string
  role: UserRole
  is_active: boolean
  is_platform_admin: boolean
  channel_ids: string[]
  created_at: string
}

export interface ActiveTenantUser {
  id: string
  name: string
  role: UserRole
  channel_ids: string[]
}

export interface SyncRun {
  id: string
  channel_id: string
  sync_type: SyncType
  status: SyncStatus
  recent_days: number
  total_items: number
  contact_items: number
  group_items: number
  message_event_items: number
  imported_group_items: number
  processed_items: number
  succeeded_items: number
  failed_items: number
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface Channel {
  id: string
  name: string
  phone_number: string | null
  provider: 'evolution_go' | 'meta_cloud' | 'bsp'
  status: ChannelStatus
  provider_config: Record<string, unknown>
}

export interface OperationalChannelHealth {
  id: string
  name: string
  phone_number: string | null
  status: ChannelStatus
  last_event_at: string | null
  pending_events: number
  failed_events: number
  webhook_stale: boolean
}

export interface WebhookReconcileRuntime {
  active: boolean
  heartbeat_at: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_error_at: string | null
  last_error: string | null
  last_scanned_channels: number
  last_checked_events: number
  last_resolved_events: number
}

export interface HistoryReconcileRuntime {
  active: boolean
  heartbeat_at: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_error_at: string | null
  last_error: string | null
  last_scanned_channels: number
  last_checked_threads: number
  last_requested_threads: number
  last_failed_threads: number
}

export interface OperationalHealth {
  status: OperationalStatus
  generated_at: string
  redis_available: boolean
  delivery_worker_online: boolean
  webhook_worker_online: boolean
  maintenance_worker_online: boolean
  pending_deliveries: number
  delayed_deliveries: number
  failed_deliveries_24h: number
  oldest_pending_at: string | null
  pending_inbox_events: number
  delayed_inbox_events: number
  failed_inbox_events_24h: number
  pending_provider_events: number
  failed_provider_events: number
  oldest_pending_event_at: string | null
  webhook_reconcile: WebhookReconcileRuntime
  history_reconcile: HistoryReconcileRuntime
  stale_connected_channels: number
  connected_channels: number
  total_channels: number
  issues: string[]
  channels: OperationalChannelHealth[]
}

export interface WebhookReconcileResult {
  channel_id: string | null
  scanned_channels: number
  checked_events: number
  resolved_events: number
  remaining_pending_events: number
  oldest_pending_event_at: string | null
}

export interface HistoryReconcileResult {
  channel_id: string | null
  scanned_channels: number
  checked_threads: number
  requested_threads: number
  failed_threads: number
}

export type ContactKind = 'direct' | 'group'

export interface Conversation {
  id: string
  status: ConversationStatus
  assigned_user_id: string | null
  contact_id: string
  contact_kind: ContactKind
  contact_name: string | null
  contact_phone: string
  channel_id: string
  channel_name: string
  channel_status: ChannelStatus
  last_message_at: string | null
  last_message_body: string | null
  last_message_type: Message['message_type'] | null
  last_message_direction: Message['direction'] | null
  unread_count: number
  is_bot_active: boolean
  bot_handoff_at: string | null
  bot_handoff_reason: string | null
}

export interface GroupMemberResponse {
  phone_number: string
  provider_jid: string | null
  name: string | null
  is_admin: boolean
}

export interface ContactDetail {
  id: string
  kind: ContactKind
  display_name: string
  name: string | null
  address_book_name: string | null
  push_name: string | null
  business_name: string | null
  verified_name: string | null
  phone_number: string
  about: string | null
  profile_picture_url: string | null
  is_on_whatsapp: boolean | null
  profile_synced_at: string | null
  profile_sync_error: string | null
  group_member_count: number | null
  group_members: GroupMemberResponse[]
  first_interaction_at: string | null
  last_interaction_at: string | null
  conversation_count: number
  closed_conversation_count: number
}

export interface ContactSearchResult {
  id: string
  kind: ContactKind
  display_name: string
  phone_number: string
  profile_picture_url: string | null
}

export interface ContactListItem {
  id: string
  kind: ContactKind
  display_name: string
  name: string | null
  phone_number: string
  profile_picture_url: string | null
  is_on_whatsapp: boolean | null
  profile_synced_at: string | null
  conversation_count: number
  last_interaction_at: string | null
  created_at: string
  updated_at: string
}

export interface ContactListResponse {
  items: ContactListItem[]
  total: number
  limit: number
  offset: number
}

export interface ReferencedContact {
  contact_id: string
  phone_number: string
  display_name: string
}

export interface SharedContact {
  id: string
  source_contact_id: string | null
  display_name: string
  phone_number: string
  organization: string | null
}

export interface Message {
  id: string
  conversation_id: string
  direction: 'incoming' | 'outgoing'
  message_type: MessageType
  status: MessageStatus
  body: string | null
  mentioned_phones: string[]
  mentioned_jids: string[]
  referenced_contacts: ReferencedContact[]
  shared_contacts: SharedContact[]
  reply_to_message_id: string | null
  reply_to_provider_message_id: string | null
  reply_to: {
    id: string
    direction: 'incoming' | 'outgoing'
    message_type: MessageType
    body: string | null
    sender_name: string | null
    participant_name: string | null
  } | null
  attachments: MessageAttachment[]
  sender_name: string | null
  participant_phone: string | null
  participant_name: string | null
  provider_message_id: string | null
  error: string | null
  attempt_count: number
  last_attempt_at: string | null
  sent_at: string | null
  delivered_at: string | null
  read_at: string | null
  edited_at: string | null
  edit_content_unavailable: boolean
  is_bot: boolean
  is_internal: boolean
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

export interface AiConfigRead {
  id: string
  channel_id: string
  is_enabled: boolean
  provider: string
  model_name: string
  has_api_key: boolean
  system_prompt: string
  bot_name: string
  handoff_prompt: string
  temperature: number
  max_tokens: number
}

export interface AiConfigUpdate {
  is_enabled?: boolean
  provider?: string
  model_name?: string
  api_key?: string
  system_prompt?: string
  bot_name?: string
  handoff_prompt?: string
  temperature?: number
  max_tokens?: number
}

export interface SimulationMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface AiSimulateRequest {
  messages: SimulationMessage[]
  system_prompt?: string
  handoff_prompt?: string
}

export interface AiSimulateResponse {
  reply: string
  handoff_triggered: boolean
  handoff_reason: string | null
}

export interface AiSummaryResponse {
  summary: string
  generated_at: string
}


