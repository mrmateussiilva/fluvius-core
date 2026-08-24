<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import {
  AlertCircle,
  ArrowDown,
  ArrowLeft,
  Bot,
  CheckCircle2,
  LockKeyhole,
  MessageCircle,
  RotateCcw,
  ShieldCheck,
  UserPlus,
} from 'lucide-vue-next'
import type {
  ContactDetail,
  ContactSearchResult,
  Conversation,
  Message,
  MessageAttachment,
  MessageType,
  TenantUser,
  UserRole,
} from '../api/types'
import ChannelStatusBadge from './ChannelStatusBadge.vue'
import ContactDetailsPanel from './ContactDetailsPanel.vue'
import MediaLightbox from './MediaLightbox.vue'
import MessageBubble from './MessageBubble.vue'
import MessageComposer from './MessageComposer.vue'

const props = defineProps<{
  conversation: Conversation | null
  messages: Message[]
  contact: ContactDetail | null
  contactLoading: boolean
  contactError: string | null
  retryingMessageIds: string[]
  currentUserId: string | null
  currentUserRole: UserRole | null
  assignableUsers: TenantUser[]
  sending: boolean
  sendError: string | null
  operationLoading: boolean
  operationError: string | null
  hasMoreMessages?: boolean
  loadingOlderMessages?: boolean
}>()
const emit = defineEmits<{
  assign: [userId?: string]
  close: []
  send: [
    text: string,
    replyToMessageId: string | null,
    mentionedPhones: string[],
    mentionedJids: string[],
    referencedContactIds: string[],
    done: (accepted: boolean) => void,
  ]
  sendAttachment: [
    files: File[],
    caption: string | null,
    replyToMessageId: string | null,
    mentionedPhones: string[],
    mentionedJids: string[],
    referencedContactIds: string[],
    done: (acceptedIndexes: number[]) => void,
  ]
  sendContact: [
    contact: ContactSearchResult,
    replyToMessageId: string | null,
    done: (accepted: boolean) => void,
  ]
  retry: [messageId: string]
  read: [conversationId: string, throughMessageId: string]
  back: []
  showContact: []
  refreshContact: []
  loadOlder: []
}>()
const messageList = ref<HTMLElement | null>(null)
const assignmentTargetId = ref('')
const contactPanelOpen = ref(false)
const replyingTo = ref<Message | null>(null)
const highlightedMessageId = ref<string | null>(null)
const mediaPreview = ref<{
  attachment: MessageAttachment
  messageType: MessageType
} | null>(null)
const isNearBottom = ref(true)
const newMessagesBelow = ref(0)
const scrollPositions = new Map<
  string,
  { top: number; nearBottom: boolean }
>()
const knownMessageIds = new Map<string, Set<string>>()
let scrollReadyConversationId: string | null = null
const BOTTOM_THRESHOLD = 96
const MESSAGE_GROUP_WINDOW = 5 * 60 * 1000

const contactDisplayName = computed(
  () => props.contact?.display_name || props.conversation?.contact_name || props.conversation?.contact_phone || '',
)
const contactInitials = computed(() =>
  contactDisplayName.value
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join(''),
)
const isAssignedToCurrentUser = computed(
  () =>
    Boolean(props.currentUserId) &&
    props.conversation?.assigned_user_id === props.currentUserId,
)
const isAdmin = computed(() => props.currentUserRole === 'admin')
const eligibleAssignableUsers = computed(() =>
  props.assignableUsers.filter(
    (user) =>
      user.role === 'admin' ||
      Boolean(
        props.conversation &&
          user.channel_ids.includes(props.conversation.channel_id),
      ),
  ),
)
const assignedUser = computed(() =>
  eligibleAssignableUsers.value.find(
    (user) => user.id === props.conversation?.assigned_user_id,
  ),
)
const canOperate = computed(
  () =>
    props.conversation?.status === 'open' &&
    isAssignedToCurrentUser.value,
)
const canClaim = computed(
  () =>
    props.conversation?.status !== 'open' ||
    !props.conversation.assigned_user_id ||
    (isAdmin.value && !isAssignedToCurrentUser.value),
)
const canApplyAssignment = computed(
  () =>
    Boolean(assignmentTargetId.value) &&
    (props.conversation?.status !== 'open' ||
      assignmentTargetId.value !== props.conversation.assigned_user_id),
)
const assignmentActionLabel = computed(() => {
  if (props.conversation?.status === 'closed') return 'Atribuir e reabrir'
  return props.conversation?.assigned_user_id ? 'Transferir' : 'Atribuir'
})
const ownershipLabel = computed(() => {
  if (!props.conversation) return ''
  if (props.conversation.status === 'closed') return 'Atendimento finalizado'
  if (!props.conversation.assigned_user_id) return 'Aguardando atendente'
  if (isAssignedToCurrentUser.value) return 'Em atendimento por você'
  return assignedUser.value
    ? `Em atendimento por ${assignedUser.value.name}`
    : 'Em atendimento por outro agente'
})
const composerDisabledReason = computed(() => {
  if (!props.conversation) return 'Selecione uma conversa para responder.'
  if (props.conversation.channel_status !== 'connected') {
    return 'WhatsApp desconectado. Reconecte o canal antes de enviar mensagens.'
  }
  if (props.conversation.status === 'closed') {
    return 'Reabra e assuma o atendimento antes de responder.'
  }
  if (!props.conversation.assigned_user_id) {
    return 'Assuma este atendimento antes de responder.'
  }
  if (!isAssignedToCurrentUser.value) {
    return 'Este atendimento está com outro agente.'
  }
  return null
})
const draftStorageKey = computed(() =>
  props.currentUserId && props.conversation
    ? `fluvius_draft:${props.currentUserId}:${props.conversation.id}`
    : null,
)

watch(
  () => [
    props.conversation?.id,
    props.conversation?.assigned_user_id,
    eligibleAssignableUsers.value.map((user) => user.id).join(','),
  ],
  () => {
    const assignedUserIsAvailable = eligibleAssignableUsers.value.some(
      (user) => user.id === props.conversation?.assigned_user_id,
    )
    assignmentTargetId.value = assignedUserIsAvailable
      ? props.conversation?.assigned_user_id || ''
      : eligibleAssignableUsers.value.find(
            (user) => user.id === props.currentUserId,
          )?.id ||
        eligibleAssignableUsers.value[0]?.id ||
        ''
  },
  { immediate: true },
)

const longDateFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'long',
  year: 'numeric',
})

const dateCache = new Map<string, string>()
function dayKey(value: string) {
  let key = dateCache.get(value)
  if (!key) {
    const date = new Date(value)
    key = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
    if (dateCache.size > 2000) dateCache.clear()
    dateCache.set(value, key)
  }
  return key
}

function belongsToSameGroup(first: Message, second: Message) {
  return (
    first.direction === second.direction &&
    dayKey(first.created_at) === dayKey(second.created_at) &&
    Math.abs(
      new Date(second.created_at).getTime() -
        new Date(first.created_at).getTime(),
    ) <= MESSAGE_GROUP_WINDOW
  )
}

const retryingMessageSet = computed(
  () => new Set(props.retryingMessageIds),
)

const messageDayGroups = computed(() => {
  const groups: {
    key: string
    createdAt: string
    items: {
      message: Message
      index: number
      groupStart: boolean
      groupEnd: boolean
      spacingClass: string
    }[]
  }[] = []

  const total = props.messages.length
  props.messages.forEach((message, index) => {
    const key = dayKey(message.created_at)
    const prev = index > 0 ? props.messages[index - 1] : null
    const next = index < total - 1 ? props.messages[index + 1] : null
    const groupStart = !prev || !belongsToSameGroup(prev, message)
    const groupEnd = !next || !belongsToSameGroup(message, next)

    const item = {
      message,
      index,
      groupStart,
      groupEnd,
      spacingClass: groupStart ? 'mt-2' : 'mt-[2px]',
    }

    const currentGroup = groups.at(-1)
    if (!currentGroup || currentGroup.key !== key) {
      groups.push({
        key,
        createdAt: message.created_at,
        items: [item],
      })
      return
    }
    currentGroup.items.push(item)
  })

  return groups
})

function dateLabel(value: string) {
  const date = new Date(value)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const messageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayDifference = Math.round((today.getTime() - messageDay.getTime()) / 86_400_000)
  if (dayDifference === 0) return 'Hoje'
  if (dayDifference === 1) return 'Ontem'
  return longDateFormatter.format(date)
}

function distanceFromBottom(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight
}

function maybeMarkRead() {
  const conversation = props.conversation
  if (
    !conversation ||
    scrollReadyConversationId !== conversation.id ||
    document.visibilityState !== 'visible' ||
    !isNearBottom.value ||
    !conversation.unread_count ||
    !props.messages.length
  ) {
    return
  }
  const lastVisibleIncoming = props.messages
    .slice()
    .reverse()
    .find((message) => message.direction === 'incoming')
  if (lastVisibleIncoming) {
    emit('read', conversation.id, lastVisibleIncoming.id)
  }
}

let loadingOlder = false
async function handleScroll() {
  updateScrollState()
  const element = messageList.value
  const conversationId = props.conversation?.id
  if (!element || !conversationId) return
  if (
    element.scrollTop < 80 &&
    props.hasMoreMessages &&
    !props.loadingOlderMessages &&
    !loadingOlder
  ) {
    loadingOlder = true
    const previousScrollHeight = element.scrollHeight
    const previousScrollTop = element.scrollTop
    emit('loadOlder')
    await nextTick()
    const heightDifference = element.scrollHeight - previousScrollHeight
    if (heightDifference > 0) {
      element.scrollTop = previousScrollTop + heightDifference
    }
    loadingOlder = false
  }
}

function updateScrollState() {
  const element = messageList.value
  const conversationId = props.conversation?.id
  if (!element || !conversationId) return
  isNearBottom.value =
    distanceFromBottom(element) <= BOTTOM_THRESHOLD
  scrollPositions.set(conversationId, {
    top: element.scrollTop,
    nearBottom: isNearBottom.value,
  })
  if (isNearBottom.value) {
    newMessagesBelow.value = 0
    maybeMarkRead()
  }
}

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
  const element = messageList.value
  if (!element) return
  element.scrollTo({ top: element.scrollHeight, behavior })
  if (behavior === 'auto') updateScrollState()
}

watch(
  () => props.conversation?.id,
  async (conversationId) => {
    scrollReadyConversationId = null
    newMessagesBelow.value = 0
    replyingTo.value = null
    mediaPreview.value = null
    if (contactPanelOpen.value) emit('showContact')
    if (!conversationId) return
    const previousIds = knownMessageIds.get(conversationId)
    const added = previousIds
      ? props.messages.filter((message) => !previousIds.has(message.id))
      : []
    knownMessageIds.set(
      conversationId,
      new Set(props.messages.map((message) => message.id)),
    )
    await nextTick()
    const element = messageList.value
    if (!element) return
    const savedPosition = scrollPositions.get(conversationId)
    if (savedPosition === undefined || savedPosition.nearBottom) {
      element.scrollTop = element.scrollHeight
    } else {
      element.scrollTop = Math.min(
        savedPosition.top,
        Math.max(0, element.scrollHeight - element.clientHeight),
      )
    }
    updateScrollState()
    scrollReadyConversationId = conversationId
    if (!isNearBottom.value) {
      newMessagesBelow.value = added.filter(
        (message) => message.direction === 'incoming',
      ).length
    }
    maybeMarkRead()
  },
  { flush: 'post', immediate: true },
)

watch(
  () => [props.conversation?.id, props.messages.length, props.messages.at(-1)?.id, props.messages.at(-1)?.status],
  async ([conversationId]) => {
    if (
      !conversationId ||
      scrollReadyConversationId !== conversationId
    ) {
      return
    }
    const previousIds =
      knownMessageIds.get(conversationId as string) || new Set<string>()
    const added = props.messages.filter(
      (message) => !previousIds.has(message.id),
    )
    knownMessageIds.set(
      conversationId as string,
      new Set(props.messages.map((message) => message.id)),
    )
    if (!added.length) return
    const shouldFollow =
      isNearBottom.value ||
      added.some((message) => message.direction === 'outgoing')
    await nextTick()
    if (props.conversation?.id !== conversationId) return
    if (shouldFollow) {
      const behavior = added.some(
        (message) => message.direction === 'outgoing',
      )
        ? 'smooth'
        : 'auto'
      scrollToBottom(behavior)
      maybeMarkRead()
      return
    }
    newMessagesBelow.value += added.filter(
      (message) => message.direction === 'incoming',
    ).length
  },
  { flush: 'pre' },
)

watch(
  [
    () => props.conversation?.id,
    () => props.conversation?.unread_count,
  ],
  async () => {
    await nextTick()
    maybeMarkRead()
  },
  { flush: 'post' },
)

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') maybeMarkRead()
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

function toggleContactPanel() {
  contactPanelOpen.value = !contactPanelOpen.value
  if (contactPanelOpen.value) emit('showContact')
}

function sendMessage(
  text: string,
  mentionedPhones: string[],
  mentionedJids: string[],
  referencedContactIds: string[],
  done: (accepted: boolean) => void,
) {
  const conversationId = props.conversation?.id
  const reply = replyingTo.value
  replyingTo.value = null
  emit(
    'send',
    text,
    reply?.id || null,
    mentionedPhones,
    mentionedJids,
    referencedContactIds,
    (accepted) => {
      if (
        !accepted &&
        props.conversation?.id === conversationId &&
        !replyingTo.value
      ) {
        replyingTo.value = reply
      }
      done(accepted)
    },
  )
}

function sendAttachment(
  files: File[],
  caption: string | null,
  mentionedPhones: string[],
  mentionedJids: string[],
  referencedContactIds: string[],
  done: (acceptedIndexes: number[]) => void,
) {
  const conversationId = props.conversation?.id
  const reply = replyingTo.value
  replyingTo.value = null
  emit(
    'sendAttachment',
    files,
    caption,
    reply?.id || null,
    mentionedPhones,
    mentionedJids,
    referencedContactIds,
    (acceptedIndexes) => {
      if (
        !acceptedIndexes.includes(0) &&
        props.conversation?.id === conversationId &&
        !replyingTo.value
      ) {
        replyingTo.value = reply
      }
      done(acceptedIndexes)
    },
  )
}

function sendContact(
  contact: ContactSearchResult,
  done: (accepted: boolean) => void,
) {
  const conversationId = props.conversation?.id
  const reply = replyingTo.value
  replyingTo.value = null
  emit('sendContact', contact, reply?.id || null, (accepted) => {
    if (
      !accepted &&
      props.conversation?.id === conversationId &&
      !replyingTo.value
    ) {
      replyingTo.value = reply
    }
    done(accepted)
  })
}

function jumpToMessage(messageId: string) {
  document.getElementById(`message-${messageId}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
  })
  highlightedMessageId.value = messageId
  window.setTimeout(() => {
    if (highlightedMessageId.value === messageId) highlightedMessageId.value = null
  }, 1600)
}

function previewMedia(
  attachment: MessageAttachment,
  messageType: MessageType,
) {
  mediaPreview.value = { attachment, messageType }
}
</script>

<template>
  <div v-if="conversation" class="relative flex h-full w-full min-h-0 min-w-0 flex-1 overflow-hidden">
    <section class="flex h-full w-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-chat">
      <header class="z-10 flex min-h-[56px] shrink-0 items-center justify-between border-b border-line bg-panel-muted px-3 py-2 shadow-sm shadow-black/[0.04] sm:min-h-[64px] sm:px-4">
        <div class="flex min-w-0 items-center">
          <button
            class="-ml-2 mr-1 grid h-10 w-10 shrink-0 place-items-center rounded-full text-ink-secondary transition hover:bg-black/5 md:hidden"
            title="Voltar para conversas"
            @click="emit('back')"
          >
            <ArrowLeft class="h-5 w-5" />
          </button>
          <button
            class="flex min-w-0 items-center gap-3 rounded-lg text-left transition hover:opacity-75"
            @click="toggleContactPanel"
          >
            <div class="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-full bg-gradient-to-br from-fluvius-100 to-emerald-200 text-xs font-semibold text-fluvius-800 ring-1 ring-black/5">
              <img
                v-if="contact?.profile_picture_url"
                :src="contact.profile_picture_url"
                :alt="contactDisplayName"
                class="h-full w-full object-cover"
              />
              <span v-else>{{ contactInitials }}</span>
            </div>
            <div class="min-w-0">
              <h2 class="flex min-w-0 items-center gap-2 text-[15px] font-semibold text-ink">
                <span class="truncate">{{ conversation.contact_name || conversation.contact_phone }}</span>
                <span
                  v-if="(conversation.contact_kind || 'direct') === 'group'"
                  class="shrink-0 rounded-full bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
                >
                  Grupo
                </span>
              </h2>
              <p class="truncate text-[11px] text-ink-muted sm:text-xs">
                <span class="hidden sm:inline">
                  {{
                    (conversation.contact_kind || 'direct') === 'group'
                      ? 'Grupo WhatsApp'
                      : conversation.contact_phone
                  }}
                  · {{ conversation.channel_name }} ·
                </span>{{ ownershipLabel }}
              </p>
            </div>
          </button>
        </div>
        <div class="flex items-center gap-2">
          <ChannelStatusBadge class="hidden xl:inline-flex" :status="conversation.channel_status" />
          <button
            v-if="canClaim"
            class="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 text-xs font-medium text-ink shadow-sm transition hover:bg-canvas sm:px-3"
            :disabled="operationLoading"
            :title="
              conversation.status === 'closed'
                ? 'Reabrir atendimento'
                : isAdmin && conversation.assigned_user_id
                  ? 'Assumir atendimento de outro agente'
                  : 'Assumir atendimento'
            "
            @click="emit('assign')"
          >
            <RotateCcw v-if="conversation.status === 'closed'" class="h-4 w-4" />
            <UserPlus v-else class="h-4 w-4" />
            <span class="hidden sm:inline">
              {{ conversation.status === 'closed' ? 'Reabrir' : 'Assumir' }}
            </span>
          </button>
          <button
            v-if="canOperate"
            class="flex h-9 items-center gap-1.5 rounded-lg bg-fluvius-700 px-2.5 text-xs font-medium text-white shadow-sm transition hover:bg-fluvius-800 sm:px-3"
            :disabled="operationLoading"
            title="Finalizar atendimento"
            @click="emit('close')"
          >
            <CheckCircle2 class="h-4 w-4" />
            <span class="hidden sm:inline">Finalizar</span>
          </button>
          <span
            v-if="conversation.status === 'open' && !canOperate && !canClaim"
            class="flex h-9 items-center gap-1.5 rounded-lg bg-warning-soft px-2.5 text-xs font-medium text-warning-strong ring-1 ring-warning/20 sm:px-3"
            title="Atendimento atribuído a outro agente"
          >
            <LockKeyhole class="h-3.5 w-3.5" />
            <span class="hidden lg:inline">Outro agente</span>
          </span>
        </div>
      </header>
      <div
        v-if="isAdmin && eligibleAssignableUsers.length"
        class="z-10 flex min-h-12 items-center gap-2 border-b border-line bg-panel px-3 py-2 shadow-sm shadow-black/[0.03] sm:px-4"
      >
        <ShieldCheck class="h-4 w-4 shrink-0 text-fluvius-700" />
        <span class="hidden shrink-0 text-xs font-medium text-ink-secondary lg:inline">
          Responsável
        </span>
        <select
          v-model="assignmentTargetId"
          class="h-8 min-w-0 flex-1 rounded-lg border border-line bg-panel px-2 text-xs text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15 sm:max-w-64"
          :disabled="operationLoading"
          aria-label="Responsável pelo atendimento"
        >
          <option
            v-for="user in eligibleAssignableUsers"
            :key="user.id"
            :value="user.id"
          >
            {{ user.name }} · {{ user.role === 'admin' ? 'Administrador' : 'Atendente' }}
          </option>
        </select>
        <button
          class="h-8 shrink-0 rounded-lg bg-fluvius-700 px-3 text-xs font-medium text-white shadow-sm transition hover:bg-fluvius-800 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="operationLoading || !canApplyAssignment"
          @click="emit('assign', assignmentTargetId)"
        >
          {{ assignmentActionLabel }}
        </button>
      </div>

      <!-- AI Bot Active Banner -->
      <div
        v-if="conversation.is_bot_active"
        class="z-10 flex items-center justify-between border-b border-purple-500/20 bg-purple-50/90 px-3 py-2 text-xs text-purple-950 shadow-sm backdrop-blur-sm dark:bg-purple-950/40 dark:text-purple-200 sm:px-4"
      >
        <div class="flex items-center gap-2 font-medium">
          <Bot class="h-4 w-4 text-purple-600 dark:text-purple-400" />
          <span>Agente de IA em pré-atendimento</span>
        </div>
        <button
          v-if="canClaim"
          class="flex items-center gap-1.5 rounded-md bg-purple-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm transition hover:bg-purple-700 active:scale-95"
          @click="emit('assign')"
        >
          <UserPlus class="h-3.5 w-3.5" />
          Assumir agora
        </button>
      </div>

      <!-- AI Handoff Transbordo Info Banner -->
      <div
        v-if="conversation.bot_handoff_reason && !conversation.is_bot_active && conversation.status !== 'closed'"
        class="z-10 flex items-center gap-2 border-b border-amber-500/20 bg-amber-50/90 px-3 py-1.5 text-[11px] text-amber-950 shadow-sm backdrop-blur-sm dark:bg-amber-950/30 dark:text-amber-200 sm:px-4"
      >
        <AlertCircle class="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
        <span class="truncate"><strong>Transbordo da IA:</strong> {{ conversation.bot_handoff_reason }}</span>
      </div>

      <p
        v-if="operationError"
        class="border-b border-danger/20 bg-danger-soft px-4 py-2 text-center text-xs text-danger-strong"
      >
        {{ operationError }}
      </p>
      <div class="relative min-h-0 flex-1 overflow-hidden">
        <div
          ref="messageList"
          class="chat-wallpaper soft-scrollbar h-full overflow-y-auto px-3 py-3 sm:px-6 sm:py-4 lg:px-8"
          @scroll.passive="handleScroll"
        >
          <div class="mx-auto w-full max-w-5xl">
            <div v-if="loadingOlderMessages" class="flex justify-center py-2">
              <span class="h-4 w-4 animate-spin rounded-full border-2 border-fluvius-600 border-t-transparent" />
            </div>
            <section
              v-for="dayGroup in messageDayGroups"
              :key="dayGroup.key"
              class="relative pb-px"
            >
              <div
                class="sticky top-2 z-10 flex justify-center py-2.5"
              >
                <span class="rounded-lg bg-panel/90 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-ink-secondary shadow-sm ring-1 ring-black/[0.03] backdrop-blur-sm">
                  {{ dateLabel(dayGroup.createdAt) }}
                </span>
              </div>
              <template
                v-for="{ message, groupStart, groupEnd, spacingClass } in dayGroup.items"
                :key="message.id"
              >
                <div
                  :id="`message-${message.id}`"
                  class="message-bubble-wrapper rounded-lg transition-colors duration-500"
                  :class="[
                    spacingClass,
                    highlightedMessageId === message.id ? 'bg-warning/20 ring-4 ring-warning/20' : '',
                  ]"
                >
                  <MessageBubble
                    :message="message"
                    :retrying="retryingMessageSet.has(message.id)"
                    :group-start="groupStart"
                    :group-end="groupEnd"
                    @reply="replyingTo = $event"
                    @jump-to="jumpToMessage"
                    @preview="previewMedia"
                    @retry="emit('retry', $event)"
                  />
                </div>
              </template>
            </section>
            <div v-if="!messages.length" class="grid place-items-center py-20 text-center text-ink-muted">
              <div class="grid h-14 w-14 place-items-center rounded-full bg-panel/70 shadow-sm">
                <MessageCircle class="h-6 w-6 text-fluvius-700" />
              </div>
              <p class="mt-3 text-sm font-medium text-ink">Comece este atendimento</p>
              <p class="mt-1 max-w-xs text-xs">Envie uma mensagem para iniciar a conversa com este contato.</p>
            </div>
          </div>
        </div>
        <Transition
          enter-active-class="transition duration-200 ease-out"
          enter-from-class="opacity-0 scale-90 translate-y-2"
          enter-to-class="opacity-100 scale-100 translate-y-0"
          leave-active-class="transition duration-150 ease-in"
          leave-from-class="opacity-100 scale-100 translate-y-0"
          leave-to-class="opacity-0 scale-90 translate-y-2"
        >
          <button
            v-if="newMessagesBelow > 0"
            type="button"
            class="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full bg-fluvius-700 px-4 py-2 text-xs font-semibold text-white shadow-lg transition hover:bg-fluvius-800 active:scale-95"
            @click="scrollToBottom('smooth')"
          >
            <ArrowDown class="h-4 w-4" />
            {{ newMessagesBelow === 1 ? '1 nova mensagem' : `${newMessagesBelow} novas mensagens` }}
          </button>
          <button
            v-else-if="!isNearBottom"
            type="button"
            class="absolute bottom-4 right-4 z-10 grid h-9 w-9 place-items-center rounded-full bg-panel/90 text-ink-secondary shadow-md ring-1 ring-black/10 backdrop-blur-sm transition hover:bg-panel hover:text-ink active:scale-95"
            title="Rolar para as mensagens mais recentes"
            @click="scrollToBottom('smooth')"
          >
            <ArrowDown class="h-4 w-4" />
          </button>
        </Transition>
      </div>
      <MessageComposer
        :draft-key="draftStorageKey"
        :disabled-reason="composerDisabledReason"
        :group-members-loading="contactLoading && !contact?.group_members.length"
        :group-members="contact?.group_members || []"
        :is-group="(contact?.kind || conversation.contact_kind || 'direct') === 'group'"
        :reply-to="replyingTo"
        :sending="sending"
        :send-error="sendError"
        @cancel-reply="replyingTo = null"
        @focus="scrollToBottom('smooth')"
        @send="sendMessage"
        @send-attachment="sendAttachment"
        @send-contact="sendContact"
      />
    </section>
    <ContactDetailsPanel
      v-if="contactPanelOpen"
      :conversation="conversation"
      :contact="contact"
      :loading="contactLoading"
      :error="contactError"
      @close="contactPanelOpen = false"
      @refresh="emit('refreshContact')"
    />
    <MediaLightbox
      v-if="mediaPreview"
      :attachment="mediaPreview.attachment"
      :message-type="mediaPreview.messageType"
      @close="mediaPreview = null"
    />
  </div>
  <section v-else class="grid flex-1 place-items-center border-b-[5px] border-fluvius-600 bg-canvas px-6 text-center">
    <div>
      <div class="mx-auto grid h-20 w-20 place-items-center rounded-full bg-canvas text-ink-muted">
        <MessageCircle class="h-9 w-9" />
      </div>
      <h2 class="mt-5 text-xl font-light text-ink">Fluvius Atendimento</h2>
      <p class="mt-2 text-sm text-ink-muted">Selecione uma conversa para começar a atender.</p>
      <p class="mt-1 text-xs text-ink-faint">Suas mensagens ficam organizadas em um só lugar.</p>
    </div>
  </section>
</template>
