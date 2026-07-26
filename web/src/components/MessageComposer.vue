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
  Smile,
  Sticker,
  UploadCloud,
  X,
  Zap,
} from 'lucide-vue-next'
import type { Message } from '../api/types'
import AudioMessagePlayer from './AudioMessagePlayer.vue'
import EmojiPicker from './EmojiPicker.vue'
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
const showAttachments = ref(false)
const showEmojis = ref(false)
const attachmentAccept = ref('')
const attachmentMode = ref<'media' | 'document' | 'audio' | 'sticker'>('media')
const preparingSticker = ref(false)
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
  const extension = `.${file.name.toLowerCase().split('.').pop() || ''}`
  if (file.type === 'image/webp' || extension === '.webp') {
    return 'sticker'
  }
  if (
    file.type.startsWith('image/') ||
    ['.gif', '.jpeg', '.jpg', '.png'].includes(extension)
  ) {
    return 'image'
  }
  if (
    file.type.startsWith('video/') ||
    ['.m4v', '.mov', '.mp4', '.webm'].includes(extension)
  ) {
    return 'video'
  }
  if (
    file.type.startsWith('audio/') ||
    ['.aac', '.flac', '.m4a', '.mp3', '.oga', '.ogg', '.wav', '.weba'].includes(
      extension,
    )
  ) {
    return 'audio'
  }
  return 'document'
})
const selectedFileKindLabel = computed(
  () =>
    ({
      image: 'Imagem',
      video: 'Vídeo',
      audio: 'Áudio',
      sticker: 'Figurinha',
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
    showAttachments.value = false
    showEmojis.value = false
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
    file &&
    (file.type.startsWith('image/') ||
      file.type.startsWith('video/') ||
      file.type.startsWith('audio/'))
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
  if (isDisabled.value || props.sending || preparingSticker.value) return
  if (selectedFile.value) {
    const submittedFile = selectedFile.value
    const isSticker = selectedFileKind.value === 'sticker'
    emit('sendAttachment', submittedFile, isSticker ? null : content || null, (accepted) => {
      if (!accepted || selectedFile.value !== submittedFile) return
      clearFile()
      if (!isSticker && text.value.trim() === content) text.value = ''
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

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (!file || attachmentMode.value !== 'sticker') {
    setFile(file)
    return
  }
  if (file.size > 25 * 1024 * 1024) {
    setFile(file)
    return
  }
  preparingSticker.value = true
  fileError.value = null
  try {
    setFile(await createNativeSticker(file))
  } catch (error) {
    selectedFile.value = null
    fileError.value =
      error instanceof Error
        ? error.message
        : 'Não foi possível preparar a figurinha.'
  } finally {
    preparingSticker.value = false
  }
}

function toggleAttachmentMenu() {
  showReplies.value = false
  showEmojis.value = false
  showAttachments.value = !showAttachments.value
}

function openAttachmentPicker(
  mode: 'media' | 'document' | 'audio' | 'sticker',
  accept: string,
) {
  attachmentMode.value = mode
  attachmentAccept.value = accept
  showReplies.value = false
  showEmojis.value = false
  showAttachments.value = false
  if (fileInput.value) fileInput.value.value = ''
  nextTick(() => fileInput.value?.click())
}

async function createNativeSticker(file: File): Promise<File> {
  if (file.type === 'image/webp' || file.name.toLowerCase().endsWith('.webp')) {
    return file
  }
  if (
    !file.type.startsWith('image/') &&
    !/\.(jpe?g|png)$/i.test(file.name)
  ) {
    throw new Error('Use uma imagem PNG, JPG ou WebP para criar a figurinha.')
  }

  const bitmap = await createImageBitmap(file)
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 512
    canvas.height = 512
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Seu navegador não conseguiu preparar a figurinha.')
    const scale = Math.min(512 / bitmap.width, 512 / bitmap.height)
    const width = Math.max(1, Math.round(bitmap.width * scale))
    const height = Math.max(1, Math.round(bitmap.height * scale))
    context.imageSmoothingEnabled = true
    context.imageSmoothingQuality = 'high'
    context.drawImage(
      bitmap,
      Math.round((512 - width) / 2),
      Math.round((512 - height) / 2),
      width,
      height,
    )
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/webp', 0.86)
    })
    if (!blob || blob.type !== 'image/webp') {
      throw new Error('Este navegador não oferece conversão de figurinha para WebP.')
    }
    const baseName = file.name.replace(/\.[^.]+$/, '') || 'figurinha'
    return new File([blob], `${baseName}.webp`, {
      type: 'image/webp',
      lastModified: Date.now(),
    })
  } finally {
    bitmap.close()
  }
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

function toggleReplies() {
  showAttachments.value = false
  showEmojis.value = false
  showReplies.value = !showReplies.value
}

function toggleEmojis() {
  showReplies.value = false
  showAttachments.value = false
  showEmojis.value = !showEmojis.value
}

function insertEmoji(emoji: string) {
  const field = textarea.value
  const start = field?.selectionStart ?? text.value.length
  const end = field?.selectionEnd ?? start
  text.value = `${text.value.slice(0, start)}${emoji}${text.value.slice(end)}`
  nextTick(() => {
    resizeTextarea()
    field?.focus()
    const cursor = start + emoji.length
    field?.setSelectionRange(cursor, cursor)
  })
}

function openStickerPicker() {
  openAttachmentPicker(
    'sticker',
    'image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp',
  )
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
          v-if="(selectedFileKind === 'image' || selectedFileKind === 'sticker') && filePreviewUrl"
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
        <Sticker v-else-if="selectedFileKind === 'sticker'" class="h-5 w-5" />
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
        <p class="mt-1 text-[10px] text-[#8696a0]">
          {{
            selectedFileKind === 'sticker'
              ? 'A figurinha será enviada sem legenda.'
              : 'Você pode adicionar uma legenda abaixo.'
          }}
        </p>
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
    <AudioMessagePlayer
      v-if="selectedFile && selectedFileKind === 'audio' && filePreviewUrl"
      class="mx-auto mb-2"
      :src="filePreviewUrl"
      :file-name="selectedFile.name || 'Áudio selecionado'"
    />
    <form class="mx-auto flex max-w-5xl items-end gap-2" @submit.prevent="submit">
      <div class="relative">
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
          :class="{ 'bg-black/5 text-fluvius-700': showEmojis }"
          :disabled="isDisabled"
          title="Escolher emoji"
          :aria-expanded="showEmojis"
          @click="toggleEmojis"
        >
          <Smile class="h-5 w-5" />
        </button>
        <div
          v-if="showEmojis"
          class="fixed inset-0 z-20"
          aria-hidden="true"
          @click="showEmojis = false"
        />
        <EmojiPicker v-if="showEmojis" @select="insertEmoji" />
      </div>
      <div class="relative">
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
          :disabled="isDisabled"
          title="Respostas rápidas"
          @click="toggleReplies"
        >
          <Zap class="h-5 w-5" />
        </button>
        <QuickReplyPicker v-if="showReplies" @select="useReply" />
      </div>
      <div class="relative">
        <input
          ref="fileInput"
          class="hidden"
          type="file"
          :accept="attachmentAccept"
          @change="selectFile"
        />
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
          :disabled="isDisabled || sending"
          title="Escolher tipo de anexo"
          :aria-expanded="showAttachments"
          @click="toggleAttachmentMenu"
        >
          <Paperclip
            class="h-5 w-5 transition"
            :class="{ 'rotate-45 text-fluvius-700': showAttachments }"
          />
        </button>
        <div
          v-if="showAttachments"
          class="fixed inset-0 z-20"
          aria-hidden="true"
          @click="showAttachments = false"
        />
        <div
          v-if="showAttachments"
          class="absolute bottom-14 left-0 z-30 w-60 overflow-hidden rounded-xl bg-white py-2 text-[#3b4a54] shadow-2xl ring-1 ring-black/5"
        >
          <p class="px-4 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-wide text-[#8696a0]">
            Enviar anexo
          </p>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-[#f0f2f5]"
            @click="openAttachmentPicker('media', 'image/*,video/*')"
          >
            <span class="grid h-9 w-9 place-items-center rounded-full bg-violet-500 text-white">
              <ImageIcon class="h-5 w-5" />
            </span>
            <span>
              <span class="block font-medium">Fotos e vídeos</span>
              <span class="block text-[10px] text-[#8696a0]">JPG, PNG, GIF, MP4, MOV e WebM</span>
            </span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-[#f0f2f5]"
            @click="
              openAttachmentPicker(
                'document',
                '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip',
              )
            "
          >
            <span class="grid h-9 w-9 place-items-center rounded-full bg-sky-500 text-white">
              <FileText class="h-5 w-5" />
            </span>
            <span>
              <span class="block font-medium">Documentos</span>
              <span class="block text-[10px] text-[#8696a0]">PDF, Office, texto, CSV e ZIP</span>
            </span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-[#f0f2f5]"
            @click="
              openAttachmentPicker(
                'audio',
                'audio/*,.aac,.flac,.m4a,.mp3,.oga,.ogg,.wav,.weba',
              )
            "
          >
            <span class="grid h-9 w-9 place-items-center rounded-full bg-orange-500 text-white">
              <Music class="h-5 w-5" />
            </span>
            <span>
              <span class="block font-medium">Áudio</span>
              <span class="block text-[10px] text-[#8696a0]">AAC, MP3, OGG, WAV e outros</span>
            </span>
          </button>
        </div>
      </div>
      <button
        type="button"
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[#54656f] transition hover:bg-black/5 hover:text-emerald-600 disabled:opacity-40"
        :disabled="isDisabled || sending || preparingSticker"
        :title="preparingSticker ? 'Preparando figurinha...' : 'Enviar figurinha'"
        @click="openStickerPicker"
      >
        <span
          v-if="preparingSticker"
          class="h-4 w-4 animate-spin rounded-full border-2 border-[#8696a0]/40 border-t-[#54656f]"
        />
        <Sticker v-else class="h-5 w-5" />
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
        :disabled="
          isDisabled ||
          sending ||
          preparingSticker ||
          (!text.trim() && !selectedFile)
        "
        :title="
          preparingSticker
            ? 'Preparando figurinha...'
            : sending
              ? 'Enviando...'
              : 'Enviar'
        "
      >
        <span
          v-if="sending || preparingSticker"
          class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
        />
        <Send v-else class="h-5 w-5" />
      </button>
    </form>
  </div>
</template>
