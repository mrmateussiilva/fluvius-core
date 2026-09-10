<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleAlert, MessageSquareText, Search, Smartphone, Users, X } from 'lucide-vue-next'
import type {
  Channel,
  ContactKind,
  Conversation,
  ConversationStatus,
  MessageType,
  TenantUser,
  UserRole,
} from '../api/types'

const props = defineProps<{
  conversations: Conversation[]
  selectedId: string | null
  currentUserId: string | null
  currentUserRole: UserRole | null
  assignableUsers: TenantUser[]
  channels: Channel[]
  activeChannelId: string | null
  canViewAllChannels: boolean
}>()
const emit = defineEmits<{
  select: [id: string]
  channelChange: [channelId: string | null]
}>()
type ConversationQueue = ConversationStatus | 'pending'

const activeStatus = ref<ConversationQueue>('pending')
const kindFilter = ref<'all' | ContactKind>('all')
const search = ref('')
const tabs: { label: string; value: ConversationQueue }[] = [
  { label: 'Não atendidas', value: 'pending' },
  { label: 'Em atendimento', value: 'open' },
  { label: 'Finalizadas', value: 'closed' },
]
const kindTabs: { label: string; value: 'all' | ContactKind }[] = [
  { label: 'Todos', value: 'all' },
  { label: 'Diretos', value: 'direct' },
  { label: 'Grupos', value: 'group' },
]

function isAssignedToCurrentUser(conversation: Conversation) {
  return (
    props.currentUserRole === 'admin' ||
    !props.currentUserId ||
    conversation.assigned_user_id === props.currentUserId
  )
}

function needsAttention(conversation: Conversation) {
  return (
    conversation.status === 'new' ||
    (conversation.status === 'open' &&
      isAssignedToCurrentUser(conversation) &&
      conversation.last_message_direction === 'incoming')
  )
}

function belongsToTab(conversation: Conversation, status: ConversationQueue) {
  if (status === 'pending') return needsAttention(conversation)
  if (status !== 'open') return conversation.status === status
  return (
    conversation.status === 'open' &&
    isAssignedToCurrentUser(conversation)
  )
}

function assigneeName(conversation: Conversation) {
  if (!conversation.assigned_user_id) return null
  return (
    props.assignableUsers.find(
      (user) => user.id === conversation.assigned_user_id,
    )?.name || 'Outro agente'
  )
}

const tabCounts = computed(() =>
  Object.fromEntries(
    tabs.map((tab) => [
      tab.value,
      props.conversations.filter((conversation) => belongsToTab(conversation, tab.value)).length,
    ]),
  ) as Record<ConversationQueue, number>,
)

const visible = computed(() => {
  const query = search.value.trim().toLocaleLowerCase('pt-BR')
  return props.conversations.filter((conversation) => {
    if (!belongsToTab(conversation, activeStatus.value)) return false
    if (kindFilter.value !== 'all' && (conversation.contact_kind || 'direct') !== kindFilter.value) {
      return false
    }
    if (!query) return true
    return [
      conversation.contact_name,
      conversation.contact_phone,
      conversation.last_message_body,
    ].some((value) => value?.toLocaleLowerCase('pt-BR').includes(query))
  })
})

watch(
  () => props.conversations.find((item) => item.id === props.selectedId)?.status,
  (status) => {
    const selected = props.conversations.find((item) => item.id === props.selectedId)
    if (status) activeStatus.value = selected && needsAttention(selected) ? 'pending' : status
  },
)

function attentionLabel(conversation: Conversation) {
  if (conversation.status === 'new') return 'Sem atendente'
  if (needsAttention(conversation)) return 'Aguardando resposta'
  return null
}

function displayName(conversation: Conversation) {
  return conversation.contact_name || conversation.contact_phone
}

function initials(conversation: Conversation) {
  return displayName(conversation)
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

const avatarPalette = [
  'bg-success-soft text-success-strong dark:bg-emerald-500/15 dark:text-emerald-300',
  'bg-info-soft text-info-strong dark:bg-sky-500/15 dark:text-sky-300',
  'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300',
  'bg-warning-soft text-warning-strong dark:bg-amber-500/15 dark:text-amber-300',
  'bg-danger-soft text-danger-strong dark:bg-rose-500/15 dark:text-rose-300',
]

function avatarClass(conversation: Conversation) {
  const seed = displayName(conversation)
    .split('')
    .reduce((sum, character) => sum + character.charCodeAt(0), 0)
  return avatarPalette[seed % avatarPalette.length]
}

function isGroup(conversation: Conversation) {
  return (conversation.contact_kind || 'direct') === 'group'
}

function messagePreview(conversation: Conversation) {
  const typeLabels: Record<MessageType, string> = {
    text: 'Mensagem',
    image: 'Imagem',
    document: 'Documento',
    audio: 'Áudio',
    video: 'Vídeo',
    sticker: 'Figurinha',
    contact: 'Contato',
  }
  const content =
    conversation.last_message_body ||
    (conversation.last_message_type ? typeLabels[conversation.last_message_type] : 'Sem mensagens')
  return conversation.last_message_direction === 'outgoing' ? `Você: ${content}` : content
}

function timeLabel(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const messageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayDifference = Math.round((today.getTime() - messageDay.getTime()) / 86_400_000)
  if (dayDifference === 0) {
    return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(date)
  }
  if (dayDifference === 1) return 'Ontem'
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' }).format(date)
}
</script>

<template>
  <aside class="flex h-full w-full shrink-0 flex-col border-r border-line bg-panel md:w-[372px]">
    <!-- Header -->
    <div class="border-b border-line bg-panel px-3 pb-2.5 pt-3">
      <!-- Search bar — clean like WhatsApp Web -->
      <label class="flex h-9 items-center gap-2.5 rounded-lg bg-canvas px-3 text-ink-muted transition focus-within:bg-panel focus-within:shadow-sm focus-within:ring-1 focus-within:ring-fluvius-500/30">
        <Search class="h-4 w-4 shrink-0" />
        <input
          v-model="search"
          type="search"
          placeholder="Pesquisar ou começar nova conversa"
          class="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-muted"
        />
        <button
          v-if="search"
          type="button"
          class="rounded-full p-0.5 hover:bg-line"
          title="Limpar busca"
          @click="search = ''"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </label>

      <!-- Channel selector + kind filters on the same compact row -->
      <div class="mt-2 flex items-center justify-between gap-2">
        <select
          :value="activeChannelId || ''"
          class="h-7 min-w-0 max-w-[160px] cursor-pointer truncate rounded-md bg-canvas px-2 text-[12px] font-medium text-ink-secondary outline-none transition hover:bg-panel-muted hover:text-ink"
          aria-label="Canal de atendimento"
          @change="
            emit(
              'channelChange',
              ($event.target as HTMLSelectElement).value || null,
            )
          "
        >
          <option v-if="canViewAllChannels" value="">Todos os canais</option>
          <option
            v-for="channel in channels"
            :key="channel.id"
            :value="channel.id"
          >
            {{ channel.name }}
          </option>
        </select>
        <div class="flex shrink-0 gap-0.5">
          <button
            v-for="tab in kindTabs"
            :key="tab.value"
            class="rounded-md px-2 py-1 text-[11px] font-medium transition"
            :class="
              kindFilter === tab.value
                ? 'bg-fluvius-600/15 text-fluvius-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                : 'text-ink-muted hover:bg-canvas hover:text-ink'
            "
            @click="kindFilter = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <!-- Status tabs (queue selector) -->
      <div class="soft-scrollbar mt-2 flex gap-0.5 overflow-x-auto">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] font-medium transition"
          :class="
            activeStatus === tab.value
              ? 'bg-fluvius-600/15 text-fluvius-700 dark:bg-emerald-500/20 dark:text-emerald-300'
              : 'text-ink-secondary hover:bg-canvas hover:text-ink'
          "
          @click="activeStatus = tab.value"
        >
          {{ tab.label }}
          <span
            v-if="tabCounts[tab.value]"
            class="min-w-4 rounded-full px-1.5 text-center text-[10px] font-bold leading-4"
            :class="
              activeStatus === tab.value
                ? 'bg-fluvius-700 text-white'
                : 'bg-line text-ink-secondary'
            "
          >
            {{ tabCounts[tab.value] }}
          </span>
        </button>
      </div>
    </div>

    <!-- Conversation list — WhatsApp Web style -->
    <div class="soft-scrollbar min-h-0 flex-1 overflow-y-auto">
      <button
        v-for="conversation in visible"
        :key="conversation.id"
        class="group flex w-full items-center gap-3 px-3 py-1.5 text-left transition hover:bg-canvas"
        :class="selectedId === conversation.id ? 'bg-canvas' : ''"
        @click="emit('select', conversation.id)"
      >
        <!-- Avatar -->
        <div
          class="relative grid h-[49px] w-[49px] shrink-0 place-items-center rounded-full text-[17px] font-semibold"
          :class="avatarClass(conversation)"
        >
          <Users v-if="isGroup(conversation)" class="h-5 w-5" />
          <template v-else>{{ initials(conversation) }}</template>
        </div>

        <!-- Text content -->
        <div class="min-w-0 flex-1 border-b border-line py-3 group-last:border-transparent">
          <!-- Row 1: contact name + time -->
          <div class="flex items-center gap-2">
            <span class="min-w-0 flex-1 truncate text-[15px] font-medium leading-[1.2] text-ink">
              {{ displayName(conversation) }}
            </span>
            <time
              class="shrink-0 text-[12px]"
              :class="conversation.unread_count ? 'font-semibold text-fluvius-600' : 'text-ink-muted'"
              :datetime="conversation.last_message_at || undefined"
            >
              {{ timeLabel(conversation.last_message_at) }}
            </time>
          </div>
          <!-- Row 2: message preview + unread badge -->
          <div class="mt-[3px] flex items-center gap-1.5">
            <span class="min-w-0 flex-1 truncate text-[13px] leading-[18px] text-ink-muted">
              {{ messagePreview(conversation) }}
            </span>
            <!-- Subtle dot for "needs attention" (no unread count yet) -->
            <span
              v-if="needsAttention(conversation) && !conversation.unread_count"
              class="h-2 w-2 shrink-0 rounded-full bg-fluvius-500"
              title="Aguardando resposta"
            />
            <!-- Unread count — identical to WhatsApp Web -->
            <span
              v-if="conversation.unread_count"
              class="grid min-h-[20px] min-w-[20px] shrink-0 place-items-center rounded-full bg-fluvius-600 px-1 text-[11px] font-bold text-white"
            >
              {{ conversation.unread_count > 99 ? '99+' : conversation.unread_count }}
            </span>
          </div>
        </div>
      </button>

      <!-- Empty state -->
      <div v-if="!visible.length" class="px-8 py-14 text-center text-ink-muted">
        <div class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-panel-muted">
          <MessageSquareText class="h-5 w-5" />
        </div>
        <p class="mt-3 text-sm font-medium text-ink">
          {{ search ? 'Nenhuma conversa encontrada' : 'Fila vazia por aqui' }}
        </p>
        <p class="mt-1 text-xs">
          {{ search ? 'Tente buscar por outro termo.' : 'Novas conversas aparecerão nesta lista.' }}
        </p>
      </div>
    </div>
  </aside>
</template>
