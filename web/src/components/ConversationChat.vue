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
  Copy,
  LoaderCircle,
  LockKeyhole,
  MessageCircle,
  MoreVertical,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  UserPlus,
  X,
} from 'lucide-vue-next'
import { analyzeConversation } from '../api/ai'
import type {
  AiConversationAnalysisResponse,
  ContactDetail,
  ContactSearchResult,
  Conversation,
  Message,
  MessageAttachment,
  MessageType,
  TenantUser,
  UserRole,
} from '../api/types'
import { useConversationStore } from '../stores/conversationStore'
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
  sidebarCollapsed: boolean
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
    isInternal?: boolean,
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
  toggleSidebar: []
}>()
const messageList = ref<HTMLElement | null>(null)
const assignmentTargetId = ref('')
const contactPanelOpen = ref(false)
const actionsMenuOpen = ref(false)
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
    first.is_internal === second.is_internal &&
    messageAuthorKey(first) === messageAuthorKey(second) &&
    dayKey(first.created_at) === dayKey(second.created_at) &&
    Math.abs(
      new Date(second.created_at).getTime() -
        new Date(first.created_at).getTime(),
    ) <= MESSAGE_GROUP_WINDOW
  )
}

function messageAuthorKey(message: Message) {
  if (message.direction === 'incoming') {
    return (
      message.participant_phone ||
      message.participant_name ||
      message.sender_name ||
      'incoming'
    )
  }
  return message.sender_name || (message.is_bot ? 'bot' : 'outgoing')
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
      spacingClass: groupStart ? 'mt-[10px]' : 'mt-px',
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

const summarizing = ref(false)
const summarizeError = ref<string | null>(null)
const aiAnalysis = ref<AiConversationAnalysisResponse | null>(null)
const copiedSuggestion = ref(false)
const savingAnalysis = ref(false)
const store = useConversationStore()

watch(
  () => props.conversation?.id,
  () => {
    aiAnalysis.value = null
    summarizeError.value = null
    copiedSuggestion.value = false
    savingAnalysis.value = false
  },
)

async function handleSummarize() {
  if (!props.conversation?.id || summarizing.value) return
  summarizing.value = true
  summarizeError.value = null
  aiAnalysis.value = null
  copiedSuggestion.value = false
  try {
    aiAnalysis.value = await analyzeConversation(props.conversation.id)
  } catch (err: any) {
    summarizeError.value = err?.message || 'Não foi possível analisar a conversa com IA.'
  } finally {
    summarizing.value = false
  }
}

function urgencyLabel(urgency: AiConversationAnalysisResponse['urgency']) {
  return { low: 'Baixa', normal: 'Normal', high: 'Alta' }[urgency]
}

function analysisNote() {
  if (!aiAnalysis.value) return ''
  const analysis = aiAnalysis.value
  return [
    '🤖 Análise do atendimento',
    '',
    `Resumo: ${analysis.summary}`,
    `Intenção do cliente: ${analysis.customer_intent}`,
    `Detalhes: ${analysis.key_details.join('; ') || 'Nenhum detalhe adicional'}`,
    `Próxima ação: ${analysis.next_action}`,
    `Urgência: ${urgencyLabel(analysis.urgency)}`,
    `Sugestão de resposta: ${analysis.suggested_reply}`,
  ].join('\n')
}

async function copySuggestedReply() {
  if (!aiAnalysis.value) return
  try {
    await navigator.clipboard.writeText(aiAnalysis.value.suggested_reply)
    copiedSuggestion.value = true
    setTimeout(() => {
      copiedSuggestion.value = false
    }, 2500)
  } catch {
    // fallback
  }
}

async function saveAnalysisAsInternalNote() {
  if (!aiAnalysis.value || !props.conversation?.id || savingAnalysis.value) return
  savingAnalysis.value = true
  try {
    const accepted = await store.send(analysisNote(), null, [], [], [], true)
    if (accepted) {
      aiAnalysis.value = null
    } else {
      summarizeError.value = 'Não foi possível salvar a análise como nota interna.'
    }
  } finally {
    savingAnalysis.value = false
  }
}

function dismissSummary() {
  aiAnalysis.value = null
  summarizeError.value = null
  copiedSuggestion.value = false
}

function sendMessage(
  text: string,
  mentionedPhones: string[],
  mentionedJids: string[],
  referencedContactIds: string[],
  done: (accepted: boolean) => void,
  isInternal: boolean = false,
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
    isInternal,
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
      <header class="conversation-chat-header z-10 flex min-h-[58px] shrink-0 items-center justify-between border-b border-line bg-panel px-3 py-2 sm:px-4">
        <div class="flex min-w-0 items-center">
          <button
            type="button"
            class="mr-2 hidden h-9 w-9 shrink-0 place-items-center rounded-full text-ink-muted transition hover:bg-panel-muted hover:text-ink md:grid"
            :title="sidebarCollapsed ? 'Abrir lista de conversas' : 'Recolher lista de conversas'"
            :aria-label="sidebarCollapsed ? 'Abrir lista de conversas' : 'Recolher lista de conversas'"
            :aria-expanded="!sidebarCollapsed"
            aria-controls="conversation-sidebar"
            @click="emit('toggleSidebar')"
          >
            <PanelLeftOpen v-if="sidebarCollapsed" class="h-[18px] w-[18px]" />
            <PanelLeftClose v-else class="h-[18px] w-[18px]" />
          </button>
          <button
            class="-ml-2 mr-1 grid h-10 w-10 shrink-0 place-items-center rounded-full text-ink-secondary transition hover:bg-panel-muted md:hidden"
            title="Voltar para conversas"
            @click="emit('back')"
          >
            <ArrowLeft class="h-5 w-5" />
          </button>
          <button
            class="flex min-w-0 items-center gap-3 rounded-lg text-left transition hover:opacity-75"
            @click="toggleContactPanel"
          >
            <div class="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-full bg-fluvius-100 text-xs font-semibold text-fluvius-800 ring-1 ring-line dark:bg-panel-raised dark:text-ink dark:ring-line">
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
                  class="shrink-0 rounded-full bg-panel-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-secondary"
                >
                  Grupo
                </span>
              </h2>
              <p class="truncate text-xs text-ink-muted">
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
        <div class="relative flex items-center gap-1">
          <ChannelStatusBadge class="hidden xl:inline-flex" :status="conversation.channel_status" />
          <button
            type="button"
            class="grid h-10 w-10 place-items-center rounded-full text-ink-muted transition hover:bg-panel-muted hover:text-ink"
            title="Mais ações"
            aria-label="Mais ações da conversa"
            :aria-expanded="actionsMenuOpen"
            @click="actionsMenuOpen = !actionsMenuOpen"
          >
            <MoreVertical class="h-5 w-5" />
          </button>
          <div
            v-if="actionsMenuOpen"
            class="fixed inset-0 z-30"
            aria-hidden="true"
            @click="actionsMenuOpen = false"
          />
          <Transition name="motion-pop">
            <div
              v-if="actionsMenuOpen"
              class="absolute right-0 top-11 z-40 w-64 origin-top-right overflow-hidden rounded-lg border border-line bg-panel-raised py-1 text-ink shadow-xl"
            >
            <button
              type="button"
              class="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-panel-muted disabled:opacity-50"
              :disabled="summarizing"
              @click="actionsMenuOpen = false; handleSummarize()"
            >
              <LoaderCircle v-if="summarizing" class="h-4 w-4 animate-spin text-ink-muted" />
              <Sparkles v-else class="h-4 w-4 text-ink-muted" />
              {{ summarizing ? 'Analisando conversa…' : 'Analisar com IA' }}
            </button>
            <div v-if="isAdmin && eligibleAssignableUsers.length" class="border-y border-line px-3 py-2">
              <label class="mb-1 block text-[11px] text-ink-muted">Atribuir conversa</label>
              <select
                v-model="assignmentTargetId"
                class="h-9 w-full rounded-md border border-line bg-canvas px-2 text-sm text-ink outline-none focus:border-fluvius-500"
                :disabled="operationLoading"
                aria-label="Atribuir a..."
                @change="emit('assign', assignmentTargetId); actionsMenuOpen = false"
              >
                <option value="" disabled selected>Escolha um atendente</option>
                <option v-for="user in eligibleAssignableUsers" :key="user.id" :value="user.id">
                  {{ user.name }}
                </option>
              </select>
            </div>
            <button
              v-if="canClaim"
              type="button"
              class="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-panel-muted disabled:opacity-50"
              :disabled="operationLoading"
              @click="actionsMenuOpen = false; emit('assign')"
            >
              <RotateCcw v-if="conversation.status === 'closed'" class="h-4 w-4 text-ink-muted" />
              <UserPlus v-else class="h-4 w-4 text-ink-muted" />
              {{ conversation.status === 'closed' ? 'Reabrir atendimento' : 'Assumir atendimento' }}
            </button>
            <div
              v-if="conversation.status === 'open' && !canOperate && !canClaim"
              class="flex items-center gap-3 px-3 py-2.5 text-sm text-warning-strong"
              title="Atendimento atribuído a outro agente"
            >
              <LockKeyhole class="h-4 w-4" />Outro agente está atendendo
            </div>
            <button
              v-if="canOperate"
              type="button"
              class="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm text-danger-strong transition hover:bg-danger-soft disabled:opacity-50"
              :disabled="operationLoading"
              @click="actionsMenuOpen = false; emit('close')"
            >
              <CheckCircle2 class="h-4 w-4" />Finalizar atendimento
            </button>
            </div>
          </Transition>
        </div>
      </header>

      <!-- AI Handoff Transbordo Info Banner -->
      <div
        v-if="conversation.bot_handoff_reason && !conversation.is_bot_active && conversation.status !== 'closed'"
        class="z-10 flex items-center gap-2 border-b border-warning/20 bg-warning-soft px-3 py-1.5 text-[11px] text-warning-strong shadow-sm backdrop-blur-sm sm:px-4"
      >
        <AlertCircle class="h-3.5 w-3.5 shrink-0 text-warning-strong" />
        <span class="truncate"><strong>Transbordo da IA:</strong> {{ conversation.bot_handoff_reason }}</span>
      </div>

      <p
        v-if="operationError"
        class="border-b border-danger/20 bg-danger-soft px-4 py-2 text-center text-xs text-danger-strong"
      >
        {{ operationError }}
      </p>
      <div class="relative min-h-0 flex-1 overflow-hidden">
        <Transition name="motion-pop">
          <section
            v-if="summarizing || aiAnalysis || summarizeError"
            class="absolute inset-x-3 top-3 z-20 max-h-[min(70vh,28rem)] overflow-y-auto rounded-xl border border-line bg-panel-raised/95 p-4 shadow-xl backdrop-blur sm:inset-x-auto sm:right-4 sm:w-[min(30rem,calc(100%-2rem))]"
            :aria-busy="summarizing"
            aria-labelledby="conversation-analysis-title"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="flex min-w-0 items-start gap-2.5">
                <div class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-success-soft text-success-strong">
                  <Sparkles class="h-4 w-4" />
                </div>
                <div class="min-w-0">
                  <h3 id="conversation-analysis-title" class="text-sm font-semibold text-ink">
                    Análise do atendimento
                  </h3>
                  <p class="mt-0.5 text-[11px] text-ink-muted">
                    {{ summarizing ? 'Lendo o histórico sem enviar mensagens...' : 'Copiloto de IA' }}
                  </p>
                </div>
              </div>
              <button
                v-if="!summarizing"
                type="button"
                class="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-muted transition hover:bg-panel-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-primary/30 active:scale-95"
                aria-label="Fechar análise"
                title="Fechar análise"
                @click="dismissSummary"
              >
                <X class="h-4 w-4" />
              </button>
            </div>

            <div v-if="summarizing" class="mt-4 flex items-center gap-2 rounded-lg bg-success-soft px-3 py-3 text-xs text-success-strong">
              <LoaderCircle class="h-4 w-4 animate-spin" />
              <span>A IA está organizando contexto, pendências e uma sugestão revisável.</span>
            </div>
            <p
              v-if="!summarizing && summarizeError"
              role="alert"
              class="mt-4 rounded-lg bg-danger-soft px-3 py-3 text-xs leading-5 text-danger-strong ring-1 ring-danger/15"
            >
              {{ summarizeError }}
            </p>
            <div
              v-if="!summarizing && aiAnalysis"
              class="mt-4 space-y-4 text-sm leading-6 text-ink-secondary"
            >
              <div>
                <p class="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Resumo</p>
                <p class="mt-1 text-ink-secondary">{{ aiAnalysis.summary }}</p>
              </div>
              <div class="grid gap-3 sm:grid-cols-2">
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Intenção</p>
                  <p class="mt-1 text-ink-secondary">{{ aiAnalysis.customer_intent }}</p>
                </div>
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Urgência</p>
                  <span
                    class="mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-semibold"
                    :class="aiAnalysis.urgency === 'high' ? 'bg-danger-soft text-danger-strong' : aiAnalysis.urgency === 'normal' ? 'bg-warning-soft text-warning-strong' : 'bg-info-soft text-info-strong'"
                  >
                    {{ urgencyLabel(aiAnalysis.urgency) }}
                  </span>
                </div>
              </div>
              <div v-if="aiAnalysis.key_details.length">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Detalhes importantes</p>
                <ul class="mt-1 list-disc space-y-0.5 pl-4 text-ink-secondary">
                  <li v-for="detail in aiAnalysis.key_details" :key="detail">{{ detail }}</li>
                </ul>
              </div>
              <div class="rounded-lg bg-warning-soft px-3 py-2.5">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-warning-strong">Próxima ação</p>
                <p class="mt-1 text-warning-strong">{{ aiAnalysis.next_action }}</p>
              </div>
              <div class="rounded-lg border border-success/20 bg-success-soft px-3 py-2.5">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-success-strong">Sugestão de resposta</p>
                <p class="mt-1 whitespace-pre-wrap text-ink-secondary">{{ aiAnalysis.suggested_reply }}</p>
              </div>
            </div>

            <div v-if="aiAnalysis && !summarizing" class="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
              <button
                type="button"
                class="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-panel px-3 text-xs font-medium text-ink-secondary transition hover:bg-panel-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-primary/30 active:scale-[0.98]"
                @click="copySuggestedReply"
              >
                <Copy class="h-3.5 w-3.5" />
                {{ copiedSuggestion ? 'Sugestão copiada' : 'Copiar sugestão' }}
              </button>
              <button
                type="button"
                class="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary-strong px-3 text-xs font-semibold text-white shadow-sm transition hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-primary/30 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="savingAnalysis"
                @click="saveAnalysisAsInternalNote"
              >
                <LoaderCircle v-if="savingAnalysis" class="h-3.5 w-3.5 animate-spin" />
                <span>{{ savingAnalysis ? 'Salvando...' : 'Salvar como nota interna' }}</span>
              </button>
            </div>
          </section>
        </Transition>
        <div
          ref="messageList"
          class="chat-wallpaper soft-scrollbar h-full overflow-y-auto px-3 py-2 sm:px-5 sm:py-3 lg:px-6"
          @scroll.passive="handleScroll"
        >
          <div class="w-full">
            <div v-if="loadingOlderMessages" class="flex justify-center py-2">
              <span class="h-4 w-4 animate-spin rounded-full border-2 border-fluvius-600 border-t-transparent" />
            </div>
            <section
              v-for="dayGroup in messageDayGroups"
              :key="dayGroup.key"
              class="relative pb-px"
            >
              <div
                class="sticky top-2 z-10 flex justify-center py-2"
              >
                <span class="rounded-lg bg-panel-raised/95 px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-ink-muted shadow-sm ring-1 ring-line/50 backdrop-blur-sm">
                  {{ dateLabel(dayGroup.createdAt) }}
                </span>
              </div>
              <TransitionGroup
                name="message-motion"
                tag="div"
              >
                <div
                v-for="{ message, groupStart, groupEnd, spacingClass } in dayGroup.items"
                :key="message.id"
                  :id="`message-${message.id}`"
                  class="message-bubble-wrapper motion-slow rounded-lg transition-colors"
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
              </TransitionGroup>
            </section>
            <div v-if="!messages.length" class="grid place-items-center py-20 text-center text-ink-muted">
              <div class="grid h-14 w-14 place-items-center rounded-full bg-panel/80 shadow-sm ring-1 ring-line">
                <MessageCircle class="h-6 w-6 text-fluvius-700" />
              </div>
              <p class="mt-3 text-sm font-medium text-ink">Comece este atendimento</p>
              <p class="mt-1 max-w-xs text-xs">Envie uma mensagem para iniciar a conversa com este contato.</p>
            </div>
          </div>
        </div>
        <Transition name="motion-pop">
          <button
            v-if="newMessagesBelow > 0"
            type="button"
            class="motion-interactive absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full bg-fluvius-700 px-4 py-2 text-xs font-semibold text-white shadow-lg hover:bg-fluvius-800"
            @click="scrollToBottom('smooth')"
          >
            <ArrowDown class="h-4 w-4" />
            {{ newMessagesBelow === 1 ? '1 nova mensagem' : `${newMessagesBelow} novas mensagens` }}
          </button>
          <button
            v-else-if="!isNearBottom"
            type="button"
            class="motion-interactive absolute bottom-4 right-4 z-10 grid h-9 w-9 place-items-center rounded-full bg-panel/90 text-ink-secondary shadow-md ring-1 ring-line/50 backdrop-blur-sm hover:bg-panel hover:text-ink"
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
    <Transition name="motion-pop">
      <ContactDetailsPanel
        v-if="contactPanelOpen"
        :conversation="conversation"
        :contact="contact"
        :loading="contactLoading"
        :error="contactError"
        @close="contactPanelOpen = false"
        @refresh="emit('refreshContact')"
      />
    </Transition>
    <Transition name="motion-fade">
      <MediaLightbox
        v-if="mediaPreview"
        :attachment="mediaPreview.attachment"
        :message-type="mediaPreview.messageType"
        @close="mediaPreview = null"
      />
    </Transition>
  </div>
  <section v-else class="relative grid flex-1 place-items-center border-b-[5px] border-fluvius-600 bg-chat px-6 text-center">
    <button
      v-if="sidebarCollapsed"
      type="button"
      class="absolute left-4 top-3 z-10 hidden h-9 w-9 place-items-center rounded-full text-ink-muted transition hover:bg-panel-muted hover:text-ink md:grid"
      title="Abrir lista de conversas"
      aria-label="Abrir lista de conversas"
      aria-expanded="false"
      aria-controls="conversation-sidebar"
      @click="emit('toggleSidebar')"
    >
      <PanelLeftOpen class="h-[18px] w-[18px]" />
    </button>
    <div>
      <div class="mx-auto grid h-20 w-20 place-items-center rounded-full border border-line bg-panel text-ink-secondary shadow-sm">
        <MessageCircle class="h-9 w-9" />
      </div>
      <h2 class="mt-5 text-xl font-light text-ink">Fluvius Atendimento</h2>
      <p class="mt-2 text-sm text-ink-muted">Selecione uma conversa para começar a atender.</p>
      <p class="mt-1 text-xs text-ink-faint">Suas mensagens ficam organizadas em um só lugar.</p>
    </div>
  </section>
</template>
