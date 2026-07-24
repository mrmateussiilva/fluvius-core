<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Check,
  CheckCheck,
  CircleAlert,
  Clock3,
  Download,
  FileText,
  Reply,
  RotateCcw,
} from 'lucide-vue-next'
import type { Message } from '../api/types'

const props = defineProps<{ message: Message; retrying: boolean }>()
const emit = defineEmits<{
  reply: [message: Message]
  jumpTo: [messageId: string]
  retry: [messageId: string]
}>()
const detailsOpen = ref(false)

const sentAt = computed(() => new Date(props.message.sent_at || props.message.created_at))
const timeLabel = computed(() =>
  new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(sentAt.value),
)
const fullDateLabel = computed(() =>
  new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(sentAt.value),
)
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

function dateTimeLabel(value: string | null) {
  if (!value) return 'Aguardando'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

function fileSize(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div
    class="group relative flex"
    :class="message.direction === 'outgoing' ? 'justify-end' : 'justify-start'"
  >
    <button
      v-if="message.provider_message_id && message.status !== 'failed'"
      class="self-center rounded-full bg-white/80 p-1.5 text-[#667781] opacity-0 shadow-sm transition hover:bg-white hover:text-fluvius-700 group-hover:opacity-100 focus:opacity-100"
      :class="message.direction === 'outgoing' ? 'order-first mr-1' : 'order-last ml-1'"
      title="Responder"
      @click="emit('reply', message)"
    >
      <Reply class="h-4 w-4" />
    </button>
    <div
      class="max-w-[72%] rounded-lg px-2.5 py-1.5 text-[#111b21] shadow-[0_1px_1px_rgba(11,20,26,0.13)]"
      :class="message.direction === 'outgoing' ? 'message-tail-out bg-[#d9fdd3]' : 'message-tail-in bg-white'"
    >
      <button
        v-if="message.reply_to"
        class="mb-1.5 block w-full min-w-48 rounded-md border-l-[3px] bg-black/[0.035] px-2 py-1.5 text-left text-xs transition hover:bg-black/[0.06]"
        :class="message.reply_to.direction === 'incoming' ? 'border-sky-500' : 'border-fluvius-500'"
        @click="emit('jumpTo', message.reply_to.id)"
      >
        <span class="block font-semibold" :class="message.reply_to.direction === 'incoming' ? 'text-sky-700' : 'text-fluvius-700'">
          {{ message.reply_to.direction === 'incoming' ? 'Cliente' : 'Você' }}
        </span>
        <span class="mt-0.5 block max-w-72 truncate text-[#54656f]">
          {{ message.reply_to.body || `[${message.reply_to.message_type}]` }}
        </span>
      </button>
      <div v-if="message.attachments.length" class="mb-1 space-y-1.5">
        <template v-for="attachment in message.attachments" :key="attachment.id">
          <a
            v-if="message.message_type === 'image'"
            :href="attachment.public_url"
            target="_blank"
            rel="noopener noreferrer"
            class="block overflow-hidden rounded-md bg-black/5"
            title="Abrir imagem"
          >
            <img
              :src="attachment.public_url"
              :alt="attachment.file_name"
              class="max-h-96 w-full min-w-56 object-contain"
              loading="lazy"
            />
          </a>
          <img
            v-else-if="message.message_type === 'sticker'"
            :src="attachment.public_url"
            :alt="attachment.file_name"
            class="max-h-52 max-w-52 object-contain"
            loading="lazy"
          />
          <video
            v-else-if="message.message_type === 'video'"
            class="max-h-96 w-full min-w-64 rounded-md bg-black"
            controls
            preload="metadata"
          >
            <source :src="attachment.public_url" :type="attachment.content_type" />
            Seu navegador não suporta vídeo.
          </video>
          <audio
            v-else-if="message.message_type === 'audio'"
            class="w-72 max-w-full"
            controls
            preload="metadata"
            :src="attachment.public_url"
          />
          <a
            v-else
            :href="attachment.public_url"
            target="_blank"
            rel="noopener noreferrer"
            class="flex min-w-64 items-center gap-3 rounded-lg bg-black/[0.045] p-3 transition hover:bg-black/[0.075]"
          >
            <div class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/70 text-fluvius-700">
              <FileText class="h-5 w-5" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-xs font-medium">{{ attachment.file_name }}</p>
              <p class="mt-0.5 text-[10px] text-[#667781]">{{ fileSize(attachment.size_bytes) }}</p>
            </div>
            <Download class="h-4 w-4 shrink-0 text-[#667781]" />
          </a>
        </template>
      </div>
      <p v-if="message.body" class="whitespace-pre-wrap px-0.5 text-[13.5px] leading-[19px]">{{ message.body }}</p>
      <p v-else-if="!message.attachments.length" class="px-0.5 text-[13px] italic text-[#667781]">[{{ message.message_type }}]</p>
      <p v-if="message.error" class="mt-1 rounded bg-rose-50 px-2 py-1 text-xs text-rose-700">{{ message.error }}</p>
      <button
        v-if="message.status === 'failed' && message.direction === 'outgoing'"
        class="mt-2 flex items-center gap-1 rounded-md border border-rose-200 bg-white/60 px-2 py-1 text-xs font-medium text-rose-700 hover:bg-white"
        :disabled="retrying"
        @click="emit('retry', message.id)"
      >
        <RotateCcw class="h-3.5 w-3.5" :class="retrying ? 'animate-spin' : ''" />
        {{ retrying ? 'Tentando...' : 'Tentar novamente' }}
      </button>
      <div
        class="mt-0.5 flex items-center justify-end gap-0.5 px-0.5 text-[9.5px] leading-3 text-[#667781]"
        :title="`${fullDateLabel} · ${statusLabel}`"
      >
        <time :datetime="message.sent_at || message.created_at">{{ timeLabel }}</time>
        <button
          v-if="message.direction === 'outgoing'"
          class="relative flex items-center"
          :title="`${statusLabel} · ver detalhes`"
          @click="detailsOpen = !detailsOpen"
        >
          <Clock3 v-if="message.status === 'pending'" class="h-3 w-3" :aria-label="statusLabel" />
          <Check v-else-if="message.status === 'sent'" class="h-3 w-3" :aria-label="statusLabel" />
          <CheckCheck
            v-else-if="message.status === 'delivered'"
            class="h-3 w-3"
            :aria-label="statusLabel"
          />
          <CheckCheck
            v-else-if="message.status === 'read'"
            class="h-3.5 w-3.5 text-[#53bdeb]"
            :aria-label="statusLabel"
          />
          <CircleAlert v-else class="h-3 w-3 text-rose-600" :aria-label="statusLabel" />
          <div
            v-if="detailsOpen"
            class="absolute bottom-5 right-0 z-20 w-64 rounded-xl bg-white p-3.5 text-left text-xs text-[#3b4a54] shadow-2xl ring-1 ring-black/5"
            @click.stop
          >
            <p class="border-b border-[#e9edef] pb-2 font-semibold text-[#111b21]">Detalhes da mensagem</p>
            <dl class="mt-2.5 space-y-2">
              <div class="flex justify-between gap-3"><dt class="text-[#667781]">Enviada</dt><dd>{{ dateTimeLabel(message.sent_at) }}</dd></div>
              <div class="flex justify-between gap-3"><dt class="text-[#667781]">Entregue</dt><dd>{{ dateTimeLabel(message.delivered_at) }}</dd></div>
              <div class="flex justify-between gap-3"><dt class="text-[#667781]">Lida</dt><dd>{{ dateTimeLabel(message.read_at) }}</dd></div>
              <div class="flex justify-between gap-3 border-t border-[#e9edef] pt-2"><dt class="text-[#667781]">Tentativas</dt><dd>{{ message.attempt_count }}</dd></div>
            </dl>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>
