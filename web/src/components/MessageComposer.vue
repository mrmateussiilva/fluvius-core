<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  FileText,
  Film,
  Image as ImageIcon,
  Music,
  Paperclip,
  Reply,
  Send,
  UploadCloud,
  X,
  Zap,
} from 'lucide-vue-next'
import type { Message } from '../api/types'
import QuickReplyPicker from './QuickReplyPicker.vue'

const props = defineProps<{
  draftKey: string | null
  disabledReason: string | null
  replyTo: Message | null
  sending: boolean
  sendError: string | null
}>()
const emit = defineEmits<{
  send: [text: string, done: (accepted: boolean) => void]
  sendAttachment: [
    file: File,
    caption: string | null,
    done: (accepted: boolean) => void,
  ]
  cancelReply: []
}>()
const text = ref('')
const showReplies = ref(false)
const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const fileError = ref<string | null>(null)
const filePreviewUrl = ref<string | null>(null)
const dragActive = ref(false)
const isDisabled = computed(() => Boolean(props.disabledReason))
const selectedFileKind = computed(() => {
  const file = selectedFile.value
  if (!file) return 'document'
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  if (file.type.startsWith('audio/')) return 'audio'
  return 'document'
})
const selectedFileKindLabel = computed(
  () =>
    ({
      image: 'Imagem',
      video: 'Vídeo',
      audio: 'Áudio',
      document: 'Documento',
    })[selectedFileKind.value],
)
let loadingDraft = false

watch(
  () => props.draftKey,
  (draftKey) => {
    loadingDraft = true
    try {
      text.value = draftKey
        ? localStorage.getItem(draftKey) || ''
        : ''
    } catch {
      text.value = ''
    }
    clearFile()
    showReplies.value = false
    nextTick(() => {
      resizeTextarea()
      loadingDraft = false
    })
  },
  { immediate: true },
)

watch(
  text,
  (value) => {
    if (loadingDraft || !props.draftKey) return
    try {
      if (value) localStorage.setItem(props.draftKey, value)
      else localStorage.removeItem(props.draftKey)
    } catch {
      // Storage can be unavailable in private or restricted browser contexts.
    }
  },
  { flush: 'sync' },
)

watch(selectedFile, (file) => {
  if (filePreviewUrl.value) URL.revokeObjectURL(filePreviewUrl.value)
  filePreviewUrl.value =
    file && (file.type.startsWith('image/') || file.type.startsWith('video/'))
      ? URL.createObjectURL(file)
      : null
})

onBeforeUnmount(() => {
  if (filePreviewUrl.value) URL.revokeObjectURL(filePreviewUrl.value)
})

function resizeTextarea() {
  if (!textarea.value) return
  textarea.value.style.height = '44px'
  textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 120)}px`
}

function submit() {
  const content = text.value.trim()
  if (isDisabled.value || props.sending) return
  if (selectedFile.value) {
    const submittedFile = selectedFile.value
    emit('sendAttachment', submittedFile, content || null, (accepted) => {
      if (!accepted || selectedFile.value !== submittedFile) return
      clearFile()
      if (text.value.trim() === content) text.value = ''
      nextTick(resizeTextarea)
    })
  } else {
    if (!content) return
    text.value = ''
    nextTick(resizeTextarea)
    emit('send', content, (accepted) => {
      if (accepted) return
      text.value = text.value.trim()
        ? `${content}\n${text.value}`
        : content
      nextTick(() => {
        resizeTextarea()
        textarea.value?.focus()
      })
    })
  }
}

function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  setFile(input.files?.[0] || null)
}

function setFile(file: File | null) {
  fileError.value = null
  if (file && file.size > 25 * 1024 * 1024) {
    fileError.value = 'O arquivo deve ter até 25 MB.'
    selectedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
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

function handlePaste(event: ClipboardEvent) {
  if (isDisabled.value || props.sending) return
  const file = Array.from(event.clipboardData?.files || [])[0]
  if (!file) return
  event.preventDefault()
  setFile(file)
}

function handleDragEnter() {
  if (!isDisabled.value && !props.sending) dragActive.value = true
}

function handleDragLeave(event: DragEvent) {
  const container = event.currentTarget as HTMLElement
  if (!event.relatedTarget || !container.contains(event.relatedTarget as Node)) {
    dragActive.value = false
  }
}

function handleDrop(event: DragEvent) {
  dragActive.value = false
  if (isDisabled.value || props.sending) return
  const file = event.dataTransfer?.files?.[0] || null
  if (file) setFile(file)
}
</script>

<template>
  <div
    class="relative border-t border-[#d8dcdf] bg-[#f0f2f5] px-3 py-2.5 sm:px-4"
    @dragenter.prevent="handleDragEnter"
    @dragover.prevent
    @dragleave.prevent="handleDragLeave"
    @drop.prevent="handleDrop"
  >
    <div
      v-if="dragActive"
      class="pointer-events-none absolute inset-2 z-30 grid place-items-center rounded-xl border-2 border-dashed border-fluvius-500 bg-fluvius-50/95 text-center shadow-lg backdrop-blur-sm"
    >
      <div>
        <UploadCloud class="mx-auto h-8 w-8 text-fluvius-700" />
        <p class="mt-2 text-sm font-semibold text-fluvius-800">Solte para anexar</p>
        <p class="mt-0.5 text-xs text-fluvius-700">Imagem, vídeo, áudio ou documento · até 25 MB</p>
      </div>
    </div>
    <p v-if="disabledReason" class="mx-auto mb-2.5 max-w-5xl rounded-lg bg-amber-50 px-3 py-2 text-center text-xs text-amber-800 ring-1 ring-amber-100">
      {{ disabledReason }}
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
      class="mx-auto mb-2 flex max-w-5xl items-center gap-3 overflow-hidden rounded-xl bg-white p-2 shadow-sm ring-1 ring-black/5"
    >
      <div class="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-lg bg-fluvius-50 text-fluvius-700">
        <img
          v-if="selectedFileKind === 'image' && filePreviewUrl"
          :src="filePreviewUrl"
          :alt="selectedFile.name"
          class="h-full w-full object-cover"
        />
        <video
          v-else-if="selectedFileKind === 'video' && filePreviewUrl"
          :src="filePreviewUrl"
          class="h-full w-full object-cover"
          muted
        />
        <Music v-else-if="selectedFileKind === 'audio'" class="h-5 w-5" />
        <Film v-else-if="selectedFileKind === 'video'" class="h-5 w-5" />
        <ImageIcon v-else-if="selectedFileKind === 'image'" class="h-5 w-5" />
        <FileText v-else class="h-5 w-5" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="truncate text-xs font-semibold text-[#111b21]">
          {{ selectedFile.name || 'Arquivo colado' }}
        </p>
        <p class="mt-1 text-[10px] uppercase tracking-wide text-[#667781]">
          {{ selectedFileKindLabel }} · {{ fileSize(selectedFile.size) }}
        </p>
        <p class="mt-1 text-[10px] text-[#8696a0]">Você pode adicionar uma legenda abaixo.</p>
      </div>
      <button
        type="button"
        class="rounded-full p-2 text-[#667781] transition hover:bg-[#e9edef]"
        title="Remover anexo"
        @click="clearFile"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
    <form class="mx-auto flex max-w-5xl items-end gap-2" @submit.prevent="submit">
      <div class="relative">
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
          :disabled="isDisabled"
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
        :disabled="isDisabled || sending"
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
        :disabled="isDisabled"
        @input="resizeTextarea"
        @keydown.enter.exact.prevent="submit"
        @paste="handlePaste"
      />
      <button
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-fluvius-600 text-white shadow-sm transition hover:bg-fluvius-700 disabled:cursor-not-allowed disabled:bg-[#c6cccf] disabled:shadow-none"
        :disabled="isDisabled || sending || (!text.trim() && !selectedFile)"
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
