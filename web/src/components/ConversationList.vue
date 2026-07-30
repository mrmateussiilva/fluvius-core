<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { MessageSquareText, Search, Smartphone, Users, X } from 'lucide-vue-next'
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
const activeStatus = ref<ConversationStatus>('new')
const kindFilter = ref<'all' | ContactKind>('all')
const search = ref('')
const tabs: { label: string; value: ConversationStatus }[] = [
  { label: 'Aguardando', value: 'new' },
  { label: 'Em atendimento', value: 'open' },
  { label: 'Finalizadas', value: 'closed' },
]
const kindTabs: { label: string; value: 'all' | ContactKind }[] = [
  { label: 'Todos', value: 'all' },
  { label: 'Diretos', value: 'direct' },
  { label: 'Grupos', value: 'group' },
]

function belongsToTab(conversation: Conversation, status: ConversationStatus) {
  if (status !== 'open') return conversation.status === status
  return (
    conversation.status === 'open' &&
    (props.currentUserRole === 'admin' ||
      !props.currentUserId ||
      conversation.assigned_user_id === props.currentUserId)
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
  ) as Record<ConversationStatus, number>,
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
    if (status) activeStatus.value = status
  },
)

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
  'bg-emerald-100 text-emerald-700',
  'bg-sky-100 text-sky-700',
  'bg-violet-100 text-violet-700',
  'bg-amber-100 text-amber-700',
  'bg-rose-100 text-rose-700',
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
  <aside class="flex h-full w-full shrink-0 flex-col border-r border-[#d8dcdf] bg-white md:w-[372px]">
    <div class="border-b border-[#e6e9eb] bg-[#f7f8f8] px-4 pb-3 pt-4">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-fluvius-700">Atendimento</p>
          <h1 class="mt-0.5 text-xl font-semibold tracking-tight text-[#111b21]">Conversas</h1>
        </div>
        <div class="grid h-9 w-9 place-items-center rounded-full bg-fluvius-50 text-fluvius-700" title="Central de conversas">
          <MessageSquareText class="h-[18px] w-[18px]" />
        </div>
      </div>
      <label class="mt-3 flex items-center gap-2 rounded-lg border border-[#d8dcdf] bg-white px-3 py-2 text-[#54656f]">
        <Smartphone class="h-4 w-4 shrink-0 text-fluvius-700" />
        <select
          :value="activeChannelId || ''"
          class="min-w-0 flex-1 bg-transparent text-[13px] font-medium text-[#111b21] outline-none"
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
            {{ channel.name }}{{ channel.phone_number ? ` · ${channel.phone_number}` : '' }}
          </option>
        </select>
      </label>
      <label class="mt-3 flex h-10 items-center gap-2.5 rounded-lg bg-[#e9edef] px-3 text-[#667781] transition focus-within:bg-white focus-within:shadow-sm focus-within:ring-1 focus-within:ring-fluvius-500/30">
        <Search class="h-4 w-4 shrink-0" />
        <input
          v-model="search"
          type="search"
          placeholder="Buscar por nome, número ou mensagem"
          class="min-w-0 flex-1 bg-transparent text-[13px] text-[#111b21] outline-none placeholder:text-[#667781]"
        />
        <button
          v-if="search"
          type="button"
          class="rounded-full p-0.5 hover:bg-slate-200"
          title="Limpar busca"
          @click="search = ''"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </label>
      <div class="soft-scrollbar mt-3 flex gap-1.5 overflow-x-auto pb-0.5">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1.5 text-[11px] font-medium transition"
          :class="activeStatus === tab.value ? 'border-fluvius-100 bg-fluvius-50 text-fluvius-700' : 'border-transparent text-[#54656f] hover:bg-[#e9edef]'"
          @click="activeStatus = tab.value"
        >
          {{ tab.label }}
          <span
            class="min-w-4 rounded-full px-1 text-center text-[9px] leading-4"
            :class="activeStatus === tab.value ? 'bg-fluvius-600 text-white' : 'bg-[#dfe3e5] text-[#54656f]'"
          >
            {{ tabCounts[tab.value] }}
          </span>
        </button>
      </div>
      <div class="mt-2 flex gap-1">
        <button
          v-for="tab in kindTabs"
          :key="tab.value"
          class="rounded-md px-2 py-1 text-[10px] font-medium transition"
          :class="
            kindFilter === tab.value
              ? 'bg-slate-800 text-white'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          "
          @click="kindFilter = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>
    <div class="soft-scrollbar min-h-0 flex-1 overflow-y-auto">
      <button
        v-for="conversation in visible"
        :key="conversation.id"
        class="group flex w-full gap-3 px-3 py-2.5 text-left transition hover:bg-[#f5f6f6]"
        :class="selectedId === conversation.id ? 'bg-[#e9edef] hover:bg-[#e9edef]' : ''"
        @click="emit('select', conversation.id)"
      >
        <div
          class="relative grid h-12 w-12 shrink-0 place-items-center rounded-full text-sm font-semibold ring-1 ring-black/[0.03]"
          :class="avatarClass(conversation)"
        >
          <Users v-if="isGroup(conversation)" class="h-5 w-5" />
          <template v-else>{{ initials(conversation) }}</template>
        </div>
        <div class="min-w-0 flex-1 border-b border-[#edf0f1] pb-2.5 pt-0.5 group-last:border-transparent">
          <div class="flex items-center gap-2">
            <span class="min-w-0 flex-1 truncate text-[15px] font-medium text-[#111b21]">
              {{ displayName(conversation) }}
            </span>
            <span
              v-if="isGroup(conversation)"
              class="shrink-0 rounded-full bg-violet-50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-violet-700"
            >
              Grupo
            </span>
            <time
              class="shrink-0 text-[11px]"
              :class="conversation.unread_count ? 'font-medium text-fluvius-600' : 'text-[#667781]'"
              :datetime="conversation.last_message_at || undefined"
            >
              {{ timeLabel(conversation.last_message_at) }}
            </time>
          </div>
          <div class="mt-0.5 flex items-center gap-2">
            <span
              v-if="!activeChannelId"
              class="max-w-24 shrink-0 truncate rounded-full bg-sky-50 px-2 py-0.5 text-[9px] font-semibold text-sky-700"
              :title="conversation.channel_name"
            >
              {{ conversation.channel_name }}
            </span>
            <span class="min-w-0 flex-1 truncate text-[13px] leading-5 text-[#667781]">
              {{ messagePreview(conversation) }}
            </span>
            <span
              v-if="
                currentUserRole === 'admin' &&
                conversation.status === 'open' &&
                conversation.assigned_user_id
              "
              class="max-w-28 shrink-0 truncate rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-medium text-slate-600"
              :title="`Responsável: ${assigneeName(conversation)}`"
            >
              {{ assigneeName(conversation) }}
            </span>
            <span
              v-if="conversation.unread_count"
              class="grid min-h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full bg-fluvius-500 px-1 text-[9px] font-semibold text-white"
            >
              {{ conversation.unread_count > 99 ? '99+' : conversation.unread_count }}
            </span>
          </div>
        </div>
      </button>
      <div v-if="!visible.length" class="px-8 py-14 text-center text-[#667781]">
        <div class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#f0f2f5]">
          <MessageSquareText class="h-5 w-5" />
        </div>
        <p class="mt-3 text-sm font-medium text-[#3b4a54]">
          {{ search ? 'Nenhuma conversa encontrada' : 'Fila vazia por aqui' }}
        </p>
        <p class="mt-1 text-xs">
          {{ search ? 'Tente buscar por outro termo.' : 'Novas conversas aparecerão nesta lista.' }}
        </p>
      </div>
    </div>
  </aside>
</template>
