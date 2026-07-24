<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  CheckCircle2,
  LockKeyhole,
  MessageCircle,
  RotateCcw,
  UserPlus,
} from 'lucide-vue-next'
import type { ContactDetail, Conversation, Message } from '../api/types'
import ChannelStatusBadge from './ChannelStatusBadge.vue'
import ContactDetailsPanel from './ContactDetailsPanel.vue'
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
  sending: boolean
  sendError: string | null
  operationLoading: boolean
  operationError: string | null
}>()
const emit = defineEmits<{
  assign: []
  close: []
  send: [
    text: string,
    replyToMessageId: string | null,
    done: (accepted: boolean) => void,
  ]
  sendAttachment: [
    file: File,
    caption: string | null,
    replyToMessageId: string | null,
    done: (accepted: boolean) => void,
  ]
  retry: [messageId: string]
  showContact: []
  refreshContact: []
}>()
const messageList = ref<HTMLElement | null>(null)
const contactPanelOpen = ref(false)
const replyingTo = ref<Message | null>(null)
const highlightedMessageId = ref<string | null>(null)
let activeConversationId: string | null = null

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
const canOperate = computed(
  () =>
    props.conversation?.status === 'open' &&
    isAssignedToCurrentUser.value,
)
const canClaim = computed(
  () =>
    props.conversation?.status !== 'open' ||
    !props.conversation.assigned_user_id,
)
const ownershipLabel = computed(() => {
  if (!props.conversation) return ''
  if (props.conversation.status === 'closed') return 'Atendimento finalizado'
  if (!props.conversation.assigned_user_id) return 'Aguardando atendente'
  if (isAssignedToCurrentUser.value) return 'Em atendimento por você'
  return 'Em atendimento por outro agente'
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

function dayKey(value: string) {
  const date = new Date(value)
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

function showDateSeparator(index: number) {
  if (index === 0) return true
  return dayKey(props.messages[index].created_at) !== dayKey(props.messages[index - 1].created_at)
}

function dateLabel(value: string) {
  const date = new Date(value)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const messageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayDifference = Math.round((today.getTime() - messageDay.getTime()) / 86_400_000)
  if (dayDifference === 0) return 'Hoje'
  if (dayDifference === 1) return 'Ontem'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  }).format(date)
}

watch(
  [() => props.conversation?.id, () => props.messages.length],
  async ([conversationId]) => {
    const changedConversation = conversationId !== activeConversationId
    activeConversationId = conversationId || null
    await nextTick()
    messageList.value?.scrollTo({
      top: messageList.value.scrollHeight,
      behavior: changedConversation ? 'auto' : 'smooth',
    })
  },
  { flush: 'post', immediate: true },
)

watch(
  () => props.conversation?.id,
  () => {
    replyingTo.value = null
    if (contactPanelOpen.value) emit('showContact')
  },
)

function toggleContactPanel() {
  contactPanelOpen.value = !contactPanelOpen.value
  if (contactPanelOpen.value) emit('showContact')
}

function sendMessage(text: string, done: (accepted: boolean) => void) {
  const conversationId = props.conversation?.id
  const reply = replyingTo.value
  replyingTo.value = null
  emit('send', text, reply?.id || null, (accepted) => {
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

function sendAttachment(
  file: File,
  caption: string | null,
  done: (accepted: boolean) => void,
) {
  const conversationId = props.conversation?.id
  const reply = replyingTo.value
  replyingTo.value = null
  emit('sendAttachment', file, caption, reply?.id || null, (accepted) => {
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
</script>

<template>
  <div v-if="conversation" class="flex min-w-0 flex-1">
    <section class="flex min-w-0 flex-1 flex-col bg-[#efeae2]">
      <header class="z-10 flex min-h-[64px] items-center justify-between border-b border-[#d8dcdf] bg-[#f0f2f5] px-4 py-2 shadow-sm shadow-slate-900/[0.03]">
        <button
          class="flex min-w-0 items-center gap-3 rounded-lg text-left transition hover:opacity-75"
          @click="toggleContactPanel"
        >
          <div class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-fluvius-100 to-emerald-200 text-xs font-semibold text-fluvius-800 ring-1 ring-black/5">
            {{ contactInitials }}
          </div>
          <div class="min-w-0">
            <h2 class="truncate text-[15px] font-semibold text-[#111b21]">
              {{ conversation.contact_name || conversation.contact_phone }}
            </h2>
            <p class="truncate text-xs text-[#667781]">
              {{ conversation.contact_phone }} · {{ ownershipLabel }}
            </p>
          </div>
        </button>
        <div class="flex items-center gap-2">
          <ChannelStatusBadge :status="conversation.channel_status" />
          <button
            v-if="canClaim"
            class="flex items-center gap-1.5 rounded-lg border border-[#d1d7db] bg-white px-3 py-2 text-xs font-medium text-[#3b4a54] shadow-sm transition hover:bg-[#f7f8f8]"
            :disabled="operationLoading"
            @click="emit('assign')"
          >
            <RotateCcw v-if="conversation.status === 'closed'" class="h-4 w-4" />
            <UserPlus v-else class="h-4 w-4" />
            {{ conversation.status === 'closed' ? 'Reabrir' : 'Assumir' }}
          </button>
          <button
            v-if="canOperate"
            class="flex items-center gap-1.5 rounded-lg bg-fluvius-700 px-3 py-2 text-xs font-medium text-white shadow-sm transition hover:bg-fluvius-800"
            :disabled="operationLoading"
            @click="emit('close')"
          >
            <CheckCircle2 class="h-4 w-4" />
            Finalizar
          </button>
          <span
            v-if="conversation.status === 'open' && !canOperate"
            class="flex items-center gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800 ring-1 ring-amber-100"
          >
            <LockKeyhole class="h-3.5 w-3.5" />
            Outro agente
          </span>
        </div>
      </header>
      <p
        v-if="operationError"
        class="border-b border-rose-100 bg-rose-50 px-4 py-2 text-center text-xs text-rose-700"
      >
        {{ operationError }}
      </p>
      <div ref="messageList" class="chat-wallpaper soft-scrollbar flex-1 overflow-y-auto px-5 py-4 sm:px-8">
        <div class="mx-auto w-full max-w-5xl space-y-2">
          <template v-for="(message, index) in messages" :key="message.id">
            <div v-if="showDateSeparator(index)" class="flex justify-center py-2.5">
              <span class="rounded-lg bg-white/90 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-[#54656f] shadow-sm ring-1 ring-black/[0.03]">
                {{ dateLabel(message.created_at) }}
              </span>
            </div>
            <div
              :id="`message-${message.id}`"
              class="rounded-lg transition-colors duration-500"
              :class="highlightedMessageId === message.id ? 'bg-amber-200/50 ring-4 ring-amber-200/40' : ''"
            >
              <MessageBubble
                :message="message"
                :retrying="retryingMessageIds.includes(message.id)"
                @reply="replyingTo = $event"
                @jump-to="jumpToMessage"
                @retry="emit('retry', $event)"
              />
            </div>
          </template>
          <div v-if="!messages.length" class="grid place-items-center py-20 text-center text-[#667781]">
            <div class="grid h-14 w-14 place-items-center rounded-full bg-white/70 shadow-sm">
              <MessageCircle class="h-6 w-6 text-fluvius-700" />
            </div>
            <p class="mt-3 text-sm font-medium text-[#3b4a54]">Comece este atendimento</p>
            <p class="mt-1 max-w-xs text-xs">Envie uma mensagem para iniciar a conversa com este contato.</p>
          </div>
        </div>
      </div>
      <MessageComposer
        :disabled-reason="composerDisabledReason"
        :reply-to="replyingTo"
        :sending="sending"
        :send-error="sendError"
        @cancel-reply="replyingTo = null"
        @send="sendMessage"
        @send-attachment="sendAttachment"
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
  </div>
  <section v-else class="grid flex-1 place-items-center border-b-[5px] border-fluvius-600 bg-[#f7f8f8] px-6 text-center">
    <div>
      <div class="mx-auto grid h-20 w-20 place-items-center rounded-full bg-[#e9edef] text-[#667781]">
        <MessageCircle class="h-9 w-9" />
      </div>
      <h2 class="mt-5 text-xl font-light text-[#3b4a54]">Fluvius Atendimento</h2>
      <p class="mt-2 text-sm text-[#667781]">Selecione uma conversa para começar a atender.</p>
      <p class="mt-1 text-xs text-[#8696a0]">Suas mensagens ficam organizadas em um só lugar.</p>
    </div>
  </section>
</template>
