<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { FileText, Paperclip, Reply, Send, X, Zap } from 'lucide-vue-next'
import type { Message } from '../api/types'
import QuickReplyPicker from './QuickReplyPicker.vue'

const props = defineProps<{
  disabled: boolean
  replyTo: Message | null
  sending: boolean
  sendError: string | null
}>()
const emit = defineEmits<{
  send: [text: string]
  sendAttachment: [file: File, caption: string | null]
  cancelReply: []
}>()
const text = ref('')
const showReplies = ref(false)
const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const fileError = ref<string | null>(null)

function resizeTextarea() {
  if (!textarea.value) return
  textarea.value.style.height = '44px'
  textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 120)}px`
}

function submit() {
  const content = text.value.trim()
  if (props.disabled || props.sending) return
  if (selectedFile.value) {
    emit('sendAttachment', selectedFile.value, content || null)
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
  } else {
    if (!content) return
    emit('send', content)
  }
  text.value = ''
  nextTick(resizeTextarea)
}

function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  fileError.value = null
  if (file && file.size > 25 * 1024 * 1024) {
    fileError.value = 'O arquivo deve ter até 25 MB.'
    input.value = ''
    selectedFile.value = null
    return
  }
  selectedFile.value = file
}

function clearFile() {
  selectedFile.value = null
  fileError.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function fileSize(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function useReply(content: string) {
  text.value = content
  showReplies.value = false
  nextTick(() => {
    resizeTextarea()
    textarea.value?.focus()
  })
}
</script>

<template>
  <div class="border-t border-[#d8dcdf] bg-[#f0f2f5] px-4 py-2.5">
    <p v-if="disabled" class="mx-auto mb-2.5 max-w-5xl rounded-lg bg-rose-50 px-3 py-2 text-center text-xs text-rose-700 ring-1 ring-rose-100">
      WhatsApp desconectado. Reconecte o canal antes de enviar mensagens.
    </p>
    <p v-else-if="sendError || fileError" class="mx-auto mb-2.5 max-w-5xl rounded-lg bg-rose-50 px-3 py-2 text-center text-xs text-rose-700 ring-1 ring-rose-100">
      {{ fileError || sendError }}
    </p>
    <div
      v-if="replyTo"
      class="mx-auto mb-2 flex max-w-5xl items-center gap-3 rounded-lg border-l-4 border-fluvius-600 bg-white px-3 py-2 shadow-sm"
    >
      <Reply class="h-4 w-4 shrink-0 text-fluvius-600" />
      <div class="min-w-0 flex-1">
        <p class="text-xs font-semibold text-fluvius-700">
          Respondendo a {{ replyTo.direction === 'incoming' ? 'Cliente' : 'Você' }}
        </p>
        <p class="mt-0.5 truncate text-xs text-[#667781]">
          {{ replyTo.body || `[${replyTo.message_type}]` }}
        </p>
      </div>
      <button
        type="button"
        class="rounded-full p-1.5 text-[#667781] hover:bg-[#e9edef]"
        title="Cancelar resposta"
        @click="emit('cancelReply')"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
    <div
      v-if="selectedFile"
      class="mx-auto mb-2 flex max-w-5xl items-center gap-3 rounded-lg bg-white px-3 py-2 shadow-sm ring-1 ring-black/5"
    >
      <div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-fluvius-50 text-fluvius-700">
        <FileText class="h-4 w-4" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="truncate text-xs font-medium text-[#111b21]">{{ selectedFile.name }}</p>
        <p class="mt-0.5 text-[10px] text-[#667781]">{{ fileSize(selectedFile.size) }}</p>
      </div>
      <button type="button" class="rounded-full p-1.5 text-[#667781] hover:bg-[#e9edef]" title="Remover anexo" @click="clearFile">
        <X class="h-4 w-4" />
      </button>
    </div>
    <form class="mx-auto flex max-w-5xl items-end gap-2" @submit.prevent="submit">
      <div class="relative">
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
          :disabled="disabled"
          title="Respostas rápidas"
          @click="showReplies = !showReplies"
        >
          <Zap class="h-5 w-5" />
        </button>
        <QuickReplyPicker v-if="showReplies" @select="useReply" />
      </div>
      <input
        ref="fileInput"
        class="hidden"
        type="file"
        accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,.zip,.webp"
        @change="selectFile"
      />
      <button
        type="button"
        class="grid h-11 w-11 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
        :disabled="disabled || sending"
        title="Anexar imagem, áudio, vídeo, documento ou figurinha"
        @click="fileInput?.click()"
      >
        <Paperclip class="h-5 w-5" />
      </button>
      <textarea
        ref="textarea"
        v-model="text"
        rows="1"
        class="soft-scrollbar min-h-11 flex-1 resize-none rounded-2xl border-0 bg-white px-4 py-3 text-[13.5px] leading-5 text-[#111b21] shadow-sm outline-none placeholder:text-[#667781] focus:ring-1 focus:ring-fluvius-500/30 disabled:bg-[#e2e6e8]"
        placeholder="Digite uma mensagem..."
        :disabled="disabled || sending"
        @input="resizeTextarea"
        @keydown.enter.exact.prevent="submit"
      />
      <button
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-fluvius-600 text-white shadow-sm transition hover:bg-fluvius-700 disabled:cursor-not-allowed disabled:bg-[#c6cccf] disabled:shadow-none"
        :disabled="disabled || sending || (!text.trim() && !selectedFile)"
        :title="sending ? 'Enviando...' : 'Enviar'"
      >
        <span
          v-if="sending"
          class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
        />
        <Send v-else class="h-5 w-5" />
      </button>
    </form>
  </div>
</template>
