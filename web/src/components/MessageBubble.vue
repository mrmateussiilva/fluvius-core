<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Check,
  CheckCheck,
  ChevronDown,
  CircleAlert,
  Clock3,
  Copy,
  Download,
  Expand,
  FileText,
  Info,
  Phone,
  Reply,
  RotateCcw,
  UserRound,
} from 'lucide-vue-next'
import type { Message, MessageAttachment, MessageType } from '../api/types'
import AudioMessagePlayer from './AudioMessagePlayer.vue'

const timeFormatter = new Intl.DateTimeFormat('pt-BR', {
  hour: '2-digit',
  minute: '2-digit',
})
const fullDateFormatter = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'long',
  timeStyle: 'short',
})
const dateTimeFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

const props = defineProps<{
  message: Message
  retrying: boolean
  groupStart: boolean
  groupEnd: boolean
}>()
const emit = defineEmits<{
  reply: [message: Message]
  jumpTo: [messageId: string]
  retry: [messageId: string]
  preview: [attachment: MessageAttachment, messageType: MessageType]
}>()

const menuOpen = ref(false)
const detailsOpen = ref(false)
const copied = ref(false)
const sentAt = computed(() => new Date(props.message.sent_at || props.message.created_at))
const canReply = computed(
  () => Boolean(props.message.provider_message_id) && props.message.status !== 'failed',
)
const canCopy = computed(() => Boolean(props.message.body?.trim()))
const isNativeSticker = computed(
  () =>
    props.message.message_type === 'sticker' &&
    props.message.attachments.length > 0,
)
const timeLabel = computed(() => timeFormatter.format(sentAt.value))
const fullDateLabel = computed(() => fullDateFormatter.format(sentAt.value))
const statusLabel = computed(
  () =>
    ({
      pending: 'Enviando',
      sent: 'Enviada',
      delivered: 'Entregue',
      read: 'Lida',
      failed: 'Falha no envio',
    })[props.message.status],
)
const bubbleClass = computed(() => {
  const outgoing = props.message.direction === 'outgoing'
  if (isNativeSticker.value) {
    return ['!max-w-none', '!bg-transparent', '!p-0', '!shadow-none']
  }
  return [
    outgoing ? 'bg-message-out' : 'bg-message-in',
    outgoing && props.groupStart ? 'message-tail-out' : '',
    !outgoing && props.groupStart ? 'message-tail-in' : '',
    outgoing && !props.groupStart ? 'rounded-tr-[4px]' : '',
    !outgoing && !props.groupStart ? 'rounded-tl-[4px]' : '',
    outgoing && !props.groupEnd ? 'rounded-br-[4px]' : '',
    !outgoing && !props.groupEnd ? 'rounded-bl-[4px]' : '',
  ]
})

function dateTimeLabel(value: string | null) {
  if (!value) return 'Aguardando'
  return dateTimeFormatter.format(new Date(value))
}

function fileSize(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function fileExtension(fileName: string) {
  const extension = fileName.split('.').pop()
  return extension && extension !== fileName
    ? extension.slice(0, 4).toUpperCase()
    : 'DOC'
}

function closeMenu() {
  menuOpen.value = false
}

function reply() {
  closeMenu()
  emit('reply', props.message)
}

function retry() {
  closeMenu()
  emit('retry', props.message.id)
}

async function copyMessage() {
  const content = props.message.body?.trim()
  if (!content) return
  try {
    await navigator.clipboard.writeText(content)
  } catch {
    const temporary = document.createElement('textarea')
    temporary.value = content
    temporary.style.position = 'fixed'
    temporary.style.opacity = '0'
    document.body.appendChild(temporary)
    temporary.select()
    document.execCommand('copy')
    temporary.remove()
  }
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1_500)
  closeMenu()
}

function showDetails() {
  closeMenu()
  detailsOpen.value = true
}
</script>

<template>
  <div
    class="group relative flex items-end"
    :class="message.direction === 'outgoing' ? 'justify-end' : 'justify-start'"
  >
    <div
      class="relative max-w-[88%] rounded-lg px-2.5 py-1.5 text-ink shadow-[0_1px_1px_rgba(11,20,26,0.13)] sm:max-w-[76%] lg:max-w-[68%]"
      :class="bubbleClass"
    >
      <button
        type="button"
        class="absolute right-1 top-1 z-10 grid h-6 w-6 place-items-center rounded-full bg-gradient-to-l from-message-in/95 via-message-in/85 to-message-in/60 text-ink-muted opacity-100 shadow-sm transition hover:text-ink focus:opacity-100 md:opacity-0 md:group-hover:opacity-100"
        :class="
          isNativeSticker
            ? '!bg-black/45 !text-white'
            : message.direction === 'outgoing'
              ? '!from-message-out !via-message-out/90'
              : ''
        "
        title="Ações da mensagem"
        @click.stop="menuOpen = !menuOpen"
      >
        <ChevronDown class="h-4 w-4" />
      </button>

      <div v-if="message.shared_contacts.length" class="space-y-1.5">
        <div
          v-for="contact in message.shared_contacts"
          :key="contact.id"
          class="flex min-w-56 items-center gap-3 rounded-lg bg-ink/[0.045] p-3 sm:min-w-64"
        >
          <span class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-success-soft text-success-strong">
            <UserRound class="h-5 w-5" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-semibold">
              {{ contact.display_name }}
            </span>
            <span v-if="contact.organization" class="mt-0.5 block truncate text-[10px] text-ink-muted">
              {{ contact.organization }}
            </span>
            <span class="mt-0.5 block truncate text-xs text-ink-muted">
              +{{ contact.phone_number }}
            </span>
          </span>
          <a
            :href="`tel:+${contact.phone_number}`"
            class="grid h-9 w-9 shrink-0 place-items-center rounded-full text-success-strong hover:bg-success-soft"
            title="Ligar para contato"
          >
            <Phone class="h-4 w-4" />
          </a>
        </div>
      </div>

      <div
        v-if="menuOpen"
        class="fixed inset-0 z-20"
        aria-hidden="true"
        @click="closeMenu"
      />
      <div
        v-if="menuOpen"
        class="absolute right-1 top-7 z-30 w-48 overflow-hidden rounded-lg bg-panel py-1 text-[13px] text-ink shadow-2xl ring-1 ring-black/5"
      >
        <button
          v-if="canReply"
          class="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition hover:bg-panel-muted"
          @click="reply"
        >
          <Reply class="h-4 w-4" />
          Responder
        </button>
        <button
          v-if="canCopy"
          class="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition hover:bg-panel-muted"
          @click="copyMessage"
        >
          <Copy class="h-4 w-4" />
          Copiar texto
        </button>
        <button
          class="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition hover:bg-panel-muted"
          @click="showDetails"
        >
          <Info class="h-4 w-4" />
          Dados da mensagem
        </button>
        <button
          v-if="message.status === 'failed' && message.direction === 'outgoing'"
          class="flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-danger-strong transition hover:bg-danger-soft"
          :disabled="retrying"
          @click="retry"
        >
          <RotateCcw class="h-4 w-4" :class="{ 'animate-spin': retrying }" />
          {{ retrying ? 'Reenviando…' : 'Tentar novamente' }}
        </button>
      </div>

      <p
        v-if="
          message.sender_name &&
          (message.direction === 'outgoing' || message.participant_name || message.participant_phone)
        "
        class="px-0.5 text-[11px] font-semibold"
        :class="
          isNativeSticker
            ? 'absolute left-1 top-1 z-[1] rounded-full bg-black/55 px-2 py-0.5 text-white shadow-sm'
            : message.direction === 'outgoing'
              ? 'mb-0.5 pr-7 text-success-strong'
              : 'mb-0.5 pr-7 text-info-strong'
        "
      >
        {{ message.participant_name || message.sender_name }}
      </p>

      <button
        v-if="message.reply_to"
        class="mb-1.5 block w-full min-w-44 rounded-md border-l-[3px] bg-ink/[0.04] px-2 py-1.5 pr-8 text-left text-xs transition hover:bg-ink/[0.07] sm:min-w-48"
        :class="message.reply_to.direction === 'incoming' ? 'border-info' : 'border-fluvius-500'"
        @click="emit('jumpTo', message.reply_to.id)"
      >
        <span
          class="block font-semibold"
          :class="message.reply_to.direction === 'incoming' ? 'text-info-strong' : 'text-fluvius-700 dark:text-emerald-300'"
        >
          {{
            message.reply_to.direction === 'incoming'
              ? message.reply_to.participant_name ||
                message.reply_to.sender_name ||
                'Cliente'
              : message.reply_to.sender_name || 'Equipe'
          }}
        </span>
        <span class="mt-0.5 block max-w-72 truncate text-ink-secondary">
          {{ message.reply_to.body || `[${message.reply_to.message_type}]` }}
        </span>
      </button>

      <div
        v-if="message.attachments.length"
        class="space-y-1.5"
        :class="{ 'mb-1': !isNativeSticker }"
      >
        <template v-for="attachment in message.attachments" :key="attachment.id">
          <button
            v-if="message.message_type === 'image'"
            type="button"
            class="group/media relative block overflow-hidden rounded-md bg-black/5"
            title="Visualizar imagem"
            @click="emit('preview', attachment, message.message_type)"
          >
            <img
              :src="attachment.public_url"
              :alt="attachment.file_name"
              class="max-h-96 w-full min-w-48 object-cover sm:min-w-56"
              loading="lazy"
            />
            <span class="absolute right-2 top-2 grid h-8 w-8 place-items-center rounded-full bg-black/45 text-white opacity-0 backdrop-blur-sm transition group-hover/media:opacity-100">
              <Expand class="h-4 w-4" />
            </span>
          </button>

          <button
            v-else-if="message.message_type === 'sticker'"
            type="button"
            class="block"
            title="Visualizar figurinha"
            @click="emit('preview', attachment, message.message_type)"
          >
            <img
              :src="attachment.public_url"
              :alt="attachment.file_name"
              class="max-h-60 max-w-60 object-contain drop-shadow-sm"
              loading="lazy"
            />
          </button>

          <div
            v-else-if="message.message_type === 'video'"
            class="group/media relative min-w-56 overflow-hidden rounded-md bg-black sm:min-w-64"
          >
            <video
              class="max-h-96 w-full"
              controls
              preload="metadata"
              :src="attachment.public_url"
            >
              Seu navegador não suporta vídeo.
            </video>
            <button
              type="button"
              class="absolute right-2 top-2 grid h-8 w-8 place-items-center rounded-full bg-black/45 text-white opacity-0 backdrop-blur-sm transition group-hover/media:opacity-100"
              title="Ampliar vídeo"
              @click="emit('preview', attachment, message.message_type)"
            >
              <Expand class="h-4 w-4" />
            </button>
          </div>

          <AudioMessagePlayer
            v-else-if="message.message_type === 'audio'"
            :src="attachment.public_url"
            :file-name="attachment.file_name"
          />

          <a
            v-else
            :href="attachment.public_url"
            target="_blank"
            rel="noopener noreferrer"
            class="flex min-w-52 items-center gap-3 rounded-lg bg-ink/[0.045] p-3 pr-2 transition hover:bg-ink/[0.075] sm:min-w-64"
          >
            <div class="relative grid h-11 w-10 shrink-0 place-items-center rounded-md bg-panel/80 text-fluvius-700 shadow-sm">
              <FileText class="h-5 w-5" />
              <span class="absolute -bottom-1 rounded bg-fluvius-700 px-1 text-[7px] font-bold text-white">
                {{ fileExtension(attachment.file_name) }}
              </span>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-xs font-medium">{{ attachment.file_name }}</p>
              <p class="mt-0.5 text-[10px] uppercase text-ink-muted">
                {{ fileSize(attachment.size_bytes) }}
              </p>
            </div>
            <Download class="h-4 w-4 shrink-0 text-ink-muted" />
          </a>
        </template>
      </div>

      <p
        v-if="message.body"
        class="whitespace-pre-wrap break-words px-0.5 pr-5 text-[13.5px] leading-[19px]"
      >
        {{ message.body }}
      </p>
      <p
        v-else-if="!message.attachments.length && !message.shared_contacts.length"
        class="px-0.5 pr-5 text-[13px] italic text-ink-muted"
      >
        Conteúdo indisponível
      </p>

      <p
        v-if="message.edit_content_unavailable"
        class="mt-1 rounded-md bg-warning-soft/90 px-2 py-1 text-[10.5px] leading-4 text-warning-strong"
      >
        Editada no WhatsApp · o novo texto não foi disponibilizado pelo canal
      </p>

      <p
        v-if="message.error"
        class="mt-1.5 rounded-md bg-danger-soft/90 px-2 py-1.5 text-[11px] leading-4 text-danger-strong"
      >
        {{ message.error }}
      </p>
      <button
        v-if="message.status === 'failed' && message.direction === 'outgoing'"
        class="mt-1.5 flex items-center gap-1 rounded-md px-1 py-1 text-[11px] font-semibold text-danger-strong transition hover:bg-panel/50"
        :disabled="retrying"
        @click="retry"
      >
        <RotateCcw class="h-3.5 w-3.5" :class="{ 'animate-spin': retrying }" />
        {{ retrying ? 'Tentando…' : 'Não enviada · tentar novamente' }}
      </button>

      <div
        class="mt-0.5 flex items-center justify-end gap-0.5 px-0.5 text-[9.5px] leading-3 text-ink-muted"
        :class="{
          'absolute bottom-1 right-1 rounded-full bg-black/55 px-1.5 py-0.5 text-white shadow-sm':
            isNativeSticker,
        }"
        :title="`${fullDateLabel} · ${statusLabel}`"
      >
        <span v-if="copied" class="mr-1 text-fluvius-700">Copiada</span>
        <span v-if="message.edited_at" class="mr-0.5">editada</span>
        <time :datetime="message.sent_at || message.created_at">{{ timeLabel }}</time>
        <span v-if="message.direction === 'outgoing'" class="flex items-center" :title="statusLabel">
          <Clock3 v-if="message.status === 'pending'" class="h-3 w-3" :aria-label="statusLabel" />
          <Check v-else-if="message.status === 'sent'" class="h-3 w-3" :aria-label="statusLabel" />
          <CheckCheck
            v-else-if="message.status === 'delivered'"
            class="h-3 w-3"
            :aria-label="statusLabel"
          />
          <CheckCheck
            v-else-if="message.status === 'read'"
            class="h-3.5 w-3.5 text-info"
            :aria-label="statusLabel"
          />
          <CircleAlert v-else class="h-3 w-3 text-danger" :aria-label="statusLabel" />
        </span>
      </div>

      <div
        v-if="detailsOpen"
        class="fixed inset-0 z-40 bg-black/10"
        aria-hidden="true"
        @click="detailsOpen = false"
      />
      <div
        v-if="detailsOpen"
        class="absolute bottom-5 right-0 z-50 w-72 rounded-lg bg-panel p-4 text-left text-xs text-ink shadow-2xl ring-1 ring-black/5"
      >
        <div class="flex items-center justify-between border-b border-line pb-2.5">
          <p class="font-semibold text-ink">Dados da mensagem</p>
          <button
            class="rounded-full p-1 text-ink-muted hover:bg-panel-muted"
            title="Fechar"
            @click="detailsOpen = false"
          >
            <ChevronDown class="h-4 w-4" />
          </button>
        </div>
        <dl class="mt-3 space-y-2.5">
          <div class="flex justify-between gap-3">
            <dt class="text-ink-muted">Criada</dt>
            <dd class="text-right">{{ dateTimeLabel(message.created_at) }}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-ink-muted">Enviada</dt>
            <dd class="text-right">{{ dateTimeLabel(message.sent_at) }}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-ink-muted">Entregue</dt>
            <dd class="text-right">{{ dateTimeLabel(message.delivered_at) }}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-ink-muted">Lida</dt>
            <dd class="text-right">{{ dateTimeLabel(message.read_at) }}</dd>
          </div>
          <div v-if="message.edited_at" class="flex justify-between gap-3">
            <dt class="text-ink-muted">Editada</dt>
            <dd class="text-right">{{ dateTimeLabel(message.edited_at) }}</dd>
          </div>
          <div v-if="message.sender_name" class="flex justify-between gap-3">
            <dt class="text-ink-muted">Atendente</dt>
            <dd class="text-right">{{ message.sender_name }}</dd>
          </div>
          <div class="flex justify-between gap-3 border-t border-line pt-2.5">
            <dt class="text-ink-muted">Tentativas</dt>
            <dd>{{ message.attempt_count }}</dd>
          </div>
        </dl>
      </div>
    </div>
  </div>
</template>
