<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  Film,
  Image as ImageIcon,
  Mic,
  Music,
  Paperclip,
  Pause,
  Play,
  Reply,
  Send,
  Smile,
  Sticker,
  Square,
  Trash2,
  UploadCloud,
  UserRound,
  X,
  Zap,
} from 'lucide-vue-next'
import { searchContacts } from '../api/contacts'
import { listQuickReplies } from '../api/quickReplies'
import type {
  ContactSearchResult,
  GroupMemberResponse,
  Message,
  QuickReply,
} from '../api/types'
import AudioMessagePlayer from './AudioMessagePlayer.vue'
import ContactSharePicker from './ContactSharePicker.vue'
import EmojiPicker from './EmojiPicker.vue'
import GroupMentionPicker from './GroupMentionPicker.vue'
import QuickReplyPicker from './QuickReplyPicker.vue'

const props = defineProps<{
  draftKey: string | null
  disabledReason: string | null
  groupMembersLoading: boolean
  groupMembers: GroupMemberResponse[]
  isGroup: boolean
  replyTo: Message | null
  sending: boolean
  sendError: string | null
}>()
const emit = defineEmits<{
  send: [
    text: string,
    mentionedPhones: string[],
    mentionedJids: string[],
    referencedContactIds: string[],
    done: (accepted: boolean) => void,
  ]
  sendAttachment: [
    files: File[],
    caption: string | null,
    mentionedPhones: string[],
    mentionedJids: string[],
    referencedContactIds: string[],
    done: (acceptedIndexes: number[]) => void,
  ]
  sendContact: [
    contact: ContactSearchResult,
    done: (accepted: boolean) => void,
  ]
  cancelReply: []
}>()

type MentionCandidate = {
  key: string
  kind: 'member' | 'contact'
  phone_number: string
  mention_jid?: string | null
  label: string
  subtitle: string
  is_admin?: boolean
  contact_id?: string
}

type AttachmentKind = 'image' | 'video' | 'audio' | 'sticker' | 'document'

type SelectedAttachment = {
  id: string
  file: File
  kind: AttachmentKind
  previewUrl: string | null
}

const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
const MAX_ATTACHMENT_COUNT = 10
const MAX_RECORDING_SECONDS = 10 * 60

const text = ref('')
const showReplies = ref(false)
const showMentions = ref(false)
const quickReplies = ref<QuickReply[]>([])
const quickRepliesLoaded = ref(false)
const quickRepliesLoading = ref(false)
const quickRepliesError = ref<string | null>(null)
const quickReplyActiveIndex = ref(0)
const quickReplyMode = ref<'button' | 'slash' | null>(null)
const quickReplyTrigger = ref<{
  start: number
  end: number
  query: string
} | null>(null)
const mentionActiveIndex = ref(0)
const mentionTrigger = ref<{
  start: number
  end: number
  query: string
} | null>(null)
const selectedMentions = ref<MentionCandidate[]>([])
const selectedContactReferences = ref<MentionCandidate[]>([])
const contactMentionResults = ref<ContactSearchResult[]>([])
const contactSearchLoading = ref(false)
const contactSearchError = ref<string | null>(null)
let contactSearchRequest = 0
const showAttachments = ref(false)
const showContactSharePicker = ref(false)
const showEmojis = ref(false)
const attachmentAccept = ref('')
const attachmentMode = ref<'media' | 'document' | 'audio' | 'sticker'>('media')
const preparingSticker = ref(false)
const recordingState = ref<'idle' | 'recording' | 'paused'>('idle')
const recordingSeconds = ref(0)
const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedAttachments = ref<SelectedAttachment[]>([])
const selectedSharedContact = ref<ContactSearchResult | null>(null)
const fileError = ref<string | null>(null)
const dragActive = ref(false)
const isDisabled = computed(() => Boolean(props.disabledReason))
const isRecording = computed(() => recordingState.value !== 'idle')
const hasSendContent = computed(
  () =>
    Boolean(text.value.trim()) ||
    selectedAttachments.value.length > 0 ||
    selectedSharedContact.value !== null,
)
const quickReplyQuery = computed(() =>
  quickReplyMode.value === 'slash'
    ? quickReplyTrigger.value?.query || ''
    : '',
)
const filteredQuickReplies = computed(() => {
  if (!showReplies.value) return []
  return filterQuickReplies(quickReplies.value, quickReplyQuery.value)
})
const mentionQuery = computed(() => mentionTrigger.value?.query || '')
const mentionCandidates = computed(() => {
  if (!showMentions.value) return []
  return combinedMentionCandidates(mentionQuery.value)
})
function attachmentKind(file: File): AttachmentKind {
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
}

function attachmentKindLabel(kind: AttachmentKind) {
  return {
    image: 'Imagem',
    video: 'Vídeo',
    audio: 'Áudio',
    sticker: 'Figurinha',
    document: 'Documento',
  }[kind]
}
let loadingDraft = false
let draftSaveTimer: number | null = null
let activeDraftKey: string | null = null
let mediaRecorder: MediaRecorder | null = null
let recordingStream: MediaStream | null = null
let recordingChunks: Blob[] = []
let recordingBytes = 0
let recordingTimer: number | null = null
let discardRecording = false
let recordingTooLarge = false

function persistDraft(key: string | null, value: string) {
  if (!key) return
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

watch(
  () => props.draftKey,
  (draftKey, previousDraftKey) => {
    if (draftSaveTimer !== null && previousDraftKey) {
      window.clearTimeout(draftSaveTimer)
      draftSaveTimer = null
      persistDraft(previousDraftKey, text.value)
    }
    activeDraftKey = draftKey
    loadingDraft = true
    try {
      text.value = draftKey
        ? localStorage.getItem(draftKey) || ''
        : ''
    } catch {
      text.value = ''
    }
    cancelRecording()
    clearAttachments()
    selectedSharedContact.value = null
    closeQuickReplies()
    closeMentions()
    selectedMentions.value = []
    selectedContactReferences.value = []
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
    if (draftSaveTimer !== null) {
      window.clearTimeout(draftSaveTimer)
    }
    draftSaveTimer = window.setTimeout(() => {
      draftSaveTimer = null
      persistDraft(activeDraftKey || props.draftKey, value)
    }, 250)
  },
)

watch(filteredQuickReplies, (replies) => {
  if (!replies.length) {
    quickReplyActiveIndex.value = 0
    return
  }
  if (quickReplyActiveIndex.value >= replies.length) {
    quickReplyActiveIndex.value = replies.length - 1
  }
})

watch(mentionCandidates, (members) => {
  if (!members.length) {
    mentionActiveIndex.value = 0
    return
  }
  if (mentionActiveIndex.value >= members.length) {
    mentionActiveIndex.value = members.length - 1
  }
})

watch([mentionQuery, showMentions], ([query, visible]) => {
  void loadContactMentionResults(visible ? query : '')
})

onBeforeUnmount(() => {
  if (draftSaveTimer !== null) {
    window.clearTimeout(draftSaveTimer)
    draftSaveTimer = null
    persistDraft(activeDraftKey || props.draftKey, text.value)
  }
  cancelRecording()
  revokeAttachmentPreviews(selectedAttachments.value)
})

function resizeTextarea() {
  if (!textarea.value) return
  textarea.value.style.height = '44px'
  textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 120)}px`
}

function normalizeSearch(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

function normalizePhone(value: string) {
  return value.replace(/\D/g, '')
}

function isMentionablePhone(value: string) {
  const phone = normalizePhone(value)
  return phone.length >= 10 && phone.length <= 15
}

function mentionJid(value: string | null | undefined) {
  const raw = (value || '').trim()
  const lower = raw.toLowerCase()
  if (lower.endsWith('@lid')) {
    const digits = normalizePhone(raw.split('@')[0])
    return digits ? `${digits}@lid` : null
  }
  if (lower.endsWith('@s.whatsapp.net')) {
    const digits = normalizePhone(raw.split('@')[0])
    return isMentionablePhone(digits) ? `${digits}@s.whatsapp.net` : null
  }
  const digits = normalizePhone(raw)
  if (digits.length > 15) return `${digits}@lid`
  if (isMentionablePhone(digits)) return `${digits}@s.whatsapp.net`
  return null
}

function memberLabel(member: GroupMemberResponse) {
  return (member.name || member.phone_number || member.provider_jid || '')
    .replace(/\s+/g, ' ')
    .trim()
}

function contactLabel(contact: ContactSearchResult) {
  return contact.display_name.replace(/\s+/g, ' ').trim() || contact.phone_number
}

function mentionText(candidate: MentionCandidate) {
  return `@${candidate.label.replace(/\s+/g, ' ')}`
}

function groupMemberScore(member: GroupMemberResponse, query: string) {
  if (!query) return 0
  const name = normalizeSearch(member.name || '')
  const phone = normalizeSearch(member.phone_number)
  const jid = normalizeSearch(member.provider_jid || '')
  if (name.startsWith(query)) return 0
  if (phone.startsWith(query)) return 1
  if (jid.startsWith(query)) return 2
  if (name.includes(query)) return 3
  if (phone.includes(query)) return 4
  if (jid.includes(query)) return 5
  return 99
}

function filterGroupMembers(
  members: GroupMemberResponse[],
  rawQuery: string,
) {
  if (!props.isGroup) return []
  const query = normalizeSearch(rawQuery.trim())
  return members
    .map((member) => ({
      member,
      jid: mentionJid(member.provider_jid) || mentionJid(member.phone_number),
      score: groupMemberScore(member, query),
    }))
    .filter(
      (item) => isMentionablePhone(item.member.phone_number) || Boolean(item.jid),
    )
    .filter((item) => item.score < 99)
    .sort((a, b) => {
      if (a.score !== b.score) return a.score - b.score
      return memberLabel(a.member).localeCompare(memberLabel(b.member), 'pt-BR')
    })
    .map((item) => ({
      key: `member:${item.jid || normalizePhone(item.member.phone_number)}`,
      kind: 'member' as const,
      phone_number: normalizePhone(item.member.phone_number),
      mention_jid: item.jid,
      label: memberLabel(item.member),
      subtitle: `${item.member.phone_number}${item.member.is_admin ? ' · Admin' : ''}`,
      is_admin: item.member.is_admin,
    }))
}

function contactMentionCandidates(
  contacts: ContactSearchResult[],
  blockedPhones: Set<string>,
) {
  return contacts
    .filter((contact) => {
      const phone = normalizePhone(contact.phone_number)
      return isMentionablePhone(phone) && !blockedPhones.has(phone)
    })
    .map((contact) => ({
      key: `contact:${contact.id}`,
      kind: 'contact' as const,
      contact_id: contact.id,
      phone_number: normalizePhone(contact.phone_number),
      label: contactLabel(contact),
      subtitle: `${contact.phone_number} · Contato`,
    }))
}

function combinedMentionCandidates(rawQuery: string) {
  const members = filterGroupMembers(props.groupMembers, rawQuery)
  const memberPhones = new Set(members.map((member) => member.phone_number))
  return [
    ...members,
    ...contactMentionCandidates(contactMentionResults.value, memberPhones),
  ]
}

async function loadContactMentionResults(rawQuery: string) {
  const query = rawQuery.trim()
  const request = ++contactSearchRequest
  contactSearchError.value = null
  if (!props.isGroup || query.length < 2) {
    contactMentionResults.value = []
    contactSearchLoading.value = false
    return
  }
  contactSearchLoading.value = true
  try {
    const contacts = await searchContacts(query)
    if (request !== contactSearchRequest) return
    contactMentionResults.value = contacts
  } catch {
    if (request !== contactSearchRequest) return
    contactMentionResults.value = []
    contactSearchError.value = 'Não foi possível buscar contatos.'
  } finally {
    if (request === contactSearchRequest) contactSearchLoading.value = false
  }
}

function quickReplyScore(reply: QuickReply, query: string) {
  if (!query) return 0
  const shortcut = normalizeSearch(reply.shortcut)
  const title = normalizeSearch(reply.title)
  const content = normalizeSearch(reply.content)
  if (shortcut.startsWith(query)) return 0
  if (title.startsWith(query)) return 1
  if (shortcut.includes(query)) return 2
  if (title.includes(query)) return 3
  if (content.includes(query)) return 4
  return 99
}

function filterQuickReplies(replies: QuickReply[], rawQuery: string) {
  const query = normalizeSearch(rawQuery.trim())
  if (!query) return replies
  return replies
    .map((reply) => ({ reply, score: quickReplyScore(reply, query) }))
    .filter((item) => item.score < 99)
    .sort((a, b) => {
      if (a.score !== b.score) return a.score - b.score
      return a.reply.title.localeCompare(b.reply.title, 'pt-BR')
    })
    .map((item) => item.reply)
}

async function ensureQuickRepliesLoaded() {
  if (quickRepliesLoaded.value || quickRepliesLoading.value) return
  quickRepliesLoading.value = true
  quickRepliesError.value = null
  try {
    quickReplies.value = await listQuickReplies()
    quickRepliesLoaded.value = true
  } catch {
    quickReplies.value = []
    quickRepliesError.value = 'Não foi possível carregar as respostas.'
  } finally {
    quickRepliesLoading.value = false
  }
}

function currentQuickReplyTrigger() {
  const field = textarea.value
  if (!field || field.selectionStart !== field.selectionEnd) return null
  const cursor = field.selectionStart
  const beforeCursor = text.value.slice(0, cursor)
  const match = beforeCursor.match(/(^|\s)\/([^\s/]*)$/)
  if (!match) return null
  const query = match[2] || ''
  return {
    start: cursor - query.length - 1,
    end: cursor,
    query,
  }
}

function currentMentionTrigger() {
  if (!props.isGroup) return null
  const field = textarea.value
  if (!field || field.selectionStart !== field.selectionEnd) return null
  const cursor = field.selectionStart
  const beforeCursor = text.value.slice(0, cursor)
  const match = beforeCursor.match(/(^|\s)@([^@\s]*)$/)
  if (!match) return null
  const query = match[2] || ''
  return {
    start: cursor - query.length - 1,
    end: cursor,
    query,
  }
}

function closeQuickReplies() {
  showReplies.value = false
  quickReplyMode.value = null
  quickReplyTrigger.value = null
  quickReplyActiveIndex.value = 0
}

function closeMentions() {
  showMentions.value = false
  mentionTrigger.value = null
  mentionActiveIndex.value = 0
}

function updateQuickReplyTrigger() {
  const trigger = currentQuickReplyTrigger()
  quickReplyTrigger.value = trigger
  if (!trigger) {
    if (quickReplyMode.value === 'slash') closeQuickReplies()
    return
  }
  closeMentions()
  showAttachments.value = false
  showEmojis.value = false
  showReplies.value = true
  quickReplyMode.value = 'slash'
  quickReplyActiveIndex.value = 0
  void ensureQuickRepliesLoaded()
}

function updateMentionTrigger() {
  const trigger = currentMentionTrigger()
  mentionTrigger.value = trigger
  if (!trigger) {
    closeMentions()
    return
  }
  closeQuickReplies()
  showAttachments.value = false
  showEmojis.value = false
  showMentions.value = true
  mentionActiveIndex.value = 0
}

function mentionedPhonesForText(value: string) {
  return Array.from(
    new Set(
      selectedMentions.value
        .filter((candidate) => value.includes(mentionText(candidate)))
        .filter((candidate) => isMentionablePhone(candidate.phone_number))
        .map((candidate) => candidate.phone_number),
    ),
  )
}

function mentionedJidsForText(value: string) {
  return Array.from(
    new Set(
      selectedMentions.value
        .filter((candidate) => value.includes(mentionText(candidate)))
        .map((candidate) => candidate.mention_jid)
        .filter((jid): jid is string => Boolean(jid)),
    ),
  )
}

function referencedContactIdsForText(value: string) {
  return selectedContactReferences.value
    .filter((candidate) => value.includes(mentionText(candidate)))
    .map((candidate) => candidate.contact_id)
    .filter((contactId): contactId is string => Boolean(contactId))
}

function submit() {
  const content = text.value.trim()
  if (
    isDisabled.value ||
    props.sending ||
    preparingSticker.value ||
    isRecording.value
  ) {
    return
  }
  if (selectedSharedContact.value) {
    const submittedContact = selectedSharedContact.value
    emit('sendContact', submittedContact, (accepted) => {
      if (accepted && selectedSharedContact.value?.id === submittedContact.id) {
        selectedSharedContact.value = null
      }
    })
    return
  }
  if (selectedAttachments.value.length) {
    const submittedAttachments = [...selectedAttachments.value]
    const files = submittedAttachments.map((attachment) => attachment.file)
    const captionIndex = submittedAttachments.findIndex(
      (attachment) => attachment.kind !== 'sticker',
    )
    const hasCaptionTarget = captionIndex >= 0
    const submittedMentions = hasCaptionTarget ? mentionedPhonesForText(content) : []
    const submittedMentionJids = hasCaptionTarget ? mentionedJidsForText(content) : []
    const submittedContactReferences = hasCaptionTarget
      ? referencedContactIdsForText(content)
      : []
    emit(
      'sendAttachment',
      files,
      hasCaptionTarget ? content || null : null,
      submittedMentions,
      submittedMentionJids,
      submittedContactReferences,
      (acceptedIndexes) => {
        if (!acceptedIndexes.length) return
        const acceptedIds = new Set(
          acceptedIndexes.map((index) => submittedAttachments[index]?.id),
        )
        removeAcceptedAttachments(acceptedIds)
        if (
          acceptedIndexes.includes(captionIndex) &&
          text.value.trim() === content
        ) {
          text.value = ''
          selectedMentions.value = []
          selectedContactReferences.value = []
        }
        nextTick(resizeTextarea)
      },
    )
  } else {
    if (!content) return
    const submittedMentions = mentionedPhonesForText(content)
    const submittedMentionJids = mentionedJidsForText(content)
    const submittedContactReferences = referencedContactIdsForText(content)
    const submittedSelectedMentions = selectedMentions.value
    const submittedSelectedContactReferences = selectedContactReferences.value
    text.value = ''
    selectedMentions.value = []
    selectedContactReferences.value = []
    nextTick(resizeTextarea)
    emit(
      'send',
      content,
      submittedMentions,
      submittedMentionJids,
      submittedContactReferences,
      (accepted) => {
        if (accepted) return
        text.value = text.value.trim()
          ? `${content}\n${text.value}`
          : content
        selectedMentions.value = submittedSelectedMentions
        selectedContactReferences.value = submittedSelectedContactReferences
        nextTick(() => {
          resizeTextarea()
          textarea.value?.focus()
        })
      },
    )
  }
}

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return
  if (attachmentMode.value !== 'sticker') {
    addFiles(files)
    return
  }
  const file = files[0]
  if (file.size > MAX_ATTACHMENT_BYTES) {
    setSingleFile(file)
    return
  }
  preparingSticker.value = true
  fileError.value = null
  try {
    setSingleFile(await createNativeSticker(file))
  } catch (error) {
    clearAttachments()
    fileError.value =
      error instanceof Error
        ? error.message
        : 'Não foi possível preparar a figurinha.'
  } finally {
    preparingSticker.value = false
  }
}

function toggleAttachmentMenu() {
  closeQuickReplies()
  closeMentions()
  showEmojis.value = false
  showContactSharePicker.value = false
  showAttachments.value = !showAttachments.value
}

function openAttachmentPicker(
  mode: 'media' | 'document' | 'audio' | 'sticker',
  accept: string,
) {
  attachmentMode.value = mode
  attachmentAccept.value = accept
  closeQuickReplies()
  closeMentions()
  showEmojis.value = false
  showAttachments.value = false
  showContactSharePicker.value = false
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

function createSelectedAttachment(file: File): SelectedAttachment {
  const kind = attachmentKind(file)
  return {
    id: crypto.randomUUID(),
    file,
    kind,
    previewUrl:
      kind === 'document' ? null : URL.createObjectURL(file),
  }
}

function addFiles(files: File[]) {
  fileError.value = null
  selectedSharedContact.value = null
  const available = MAX_ATTACHMENT_COUNT - selectedAttachments.value.length
  if (available <= 0) {
    fileError.value = `Envie no máximo ${MAX_ATTACHMENT_COUNT} arquivos por vez.`
    return
  }
  const candidates = files.slice(0, available)
  const valid = candidates.filter((file) => file.size <= MAX_ATTACHMENT_BYTES)
  if (valid.length !== candidates.length) {
    fileError.value = 'Cada arquivo deve ter até 25 MB.'
  } else if (files.length > available) {
    fileError.value = `Somente os primeiros ${available} arquivos foram adicionados.`
  }
  selectedAttachments.value = [
    ...selectedAttachments.value,
    ...valid.map(createSelectedAttachment),
  ]
  if (fileInput.value) fileInput.value.value = ''
}

function setSingleFile(file: File) {
  if (file.size > MAX_ATTACHMENT_BYTES) {
    clearAttachments()
    fileError.value = 'O arquivo deve ter até 25 MB.'
    return
  }
  clearAttachments()
  selectedSharedContact.value = null
  selectedAttachments.value = [createSelectedAttachment(file)]
}

function revokeAttachmentPreviews(attachments: SelectedAttachment[]) {
  for (const attachment of attachments) {
    if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
  }
}

function removeAttachment(id: string) {
  const attachment = selectedAttachments.value.find((item) => item.id === id)
  if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
  selectedAttachments.value = selectedAttachments.value.filter(
    (item) => item.id !== id,
  )
  fileError.value = null
}

function removeAcceptedAttachments(acceptedIds: Set<string | undefined>) {
  const accepted = selectedAttachments.value.filter((attachment) =>
    acceptedIds.has(attachment.id),
  )
  revokeAttachmentPreviews(accepted)
  selectedAttachments.value = selectedAttachments.value.filter(
    (attachment) => !acceptedIds.has(attachment.id),
  )
}

function moveAttachment(index: number, offset: -1 | 1) {
  const target = index + offset
  if (target < 0 || target >= selectedAttachments.value.length) return
  const reordered = [...selectedAttachments.value]
  ;[reordered[index], reordered[target]] = [reordered[target], reordered[index]]
  selectedAttachments.value = reordered
}

function clearAttachments() {
  revokeAttachmentPreviews(selectedAttachments.value)
  selectedAttachments.value = []
  fileError.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function fileSize(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function recordingTime(value: number) {
  const minutes = Math.floor(value / 60)
  const seconds = value % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function supportedRecordingMimeType() {
  if (typeof MediaRecorder === 'undefined') return null
  return (
    ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((mimeType) =>
      MediaRecorder.isTypeSupported(mimeType),
    ) || ''
  )
}

async function startRecording() {
  if (
    isDisabled.value ||
    props.sending ||
    isRecording.value ||
    selectedAttachments.value.length ||
    selectedSharedContact.value
  ) {
    return
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    fileError.value = 'Este navegador não oferece gravação de áudio.'
    return
  }
  fileError.value = null
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = supportedRecordingMimeType()
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream)
    recordingStream = stream
    mediaRecorder = recorder
    recordingChunks = []
    recordingBytes = 0
    recordingSeconds.value = 0
    discardRecording = false
    recordingTooLarge = false
    recorder.addEventListener('dataavailable', (event) => {
      if (!event.data.size) return
      recordingChunks.push(event.data)
      recordingBytes += event.data.size
      if (recordingBytes > MAX_ATTACHMENT_BYTES) {
        recordingTooLarge = true
        stopRecording()
      }
    })
    recorder.addEventListener('stop', finishRecording, { once: true })
    recorder.addEventListener(
      'error',
      () => {
        discardRecording = true
        fileError.value = 'A gravação foi interrompida pelo navegador.'
        cleanupRecordingResources()
      },
      { once: true },
    )
    recorder.start(1000)
    recordingState.value = 'recording'
    recordingTimer = window.setInterval(() => {
      if (recordingState.value !== 'recording') return
      recordingSeconds.value += 1
      if (recordingSeconds.value >= MAX_RECORDING_SECONDS) stopRecording()
    }, 1000)
  } catch (error) {
    cleanupRecordingResources()
    fileError.value =
      error instanceof DOMException && error.name === 'NotAllowedError'
        ? 'Permita o acesso ao microfone para gravar áudio.'
        : 'Não foi possível iniciar a gravação de áudio.'
  }
}

function pauseRecording() {
  if (mediaRecorder?.state !== 'recording') return
  mediaRecorder.pause()
  recordingState.value = 'paused'
}

function resumeRecording() {
  if (mediaRecorder?.state !== 'paused') return
  mediaRecorder.resume()
  recordingState.value = 'recording'
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === 'inactive') return
  mediaRecorder.stop()
}

function cancelRecording() {
  discardRecording = true
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  } else {
    cleanupRecordingResources()
  }
}

function finishRecording() {
  const recorder = mediaRecorder
  const chunks = recordingChunks
  const shouldDiscard = discardRecording
  const tooLarge = recordingTooLarge
  cleanupRecordingResources()
  if (shouldDiscard) return
  if (tooLarge) {
    fileError.value = 'A gravação excedeu o limite de 25 MB.'
    return
  }
  const contentType = (recorder?.mimeType || chunks[0]?.type || 'audio/webm').split(
    ';',
    1,
  )[0]
  const blob = new Blob(chunks, { type: contentType })
  if (!blob.size) {
    fileError.value = 'A gravação não gerou áudio válido.'
    return
  }
  const extension = contentType === 'audio/mp4' ? 'm4a' : 'weba'
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
  setSingleFile(
    new File([blob], `audio-${timestamp}.${extension}`, {
      type: contentType,
      lastModified: Date.now(),
    }),
  )
}

function cleanupRecordingResources() {
  if (recordingTimer !== null) window.clearInterval(recordingTimer)
  recordingTimer = null
  recordingStream?.getTracks().forEach((track) => track.stop())
  recordingStream = null
  mediaRecorder = null
  recordingChunks = []
  recordingBytes = 0
  recordingState.value = 'idle'
  recordingSeconds.value = 0
}

function useReply(reply: QuickReply) {
  const trigger = quickReplyMode.value === 'slash' ? quickReplyTrigger.value : null
  if (trigger) {
    text.value = `${text.value.slice(0, trigger.start)}${reply.content}${text.value.slice(trigger.end)}`
  } else {
    text.value = reply.content
  }
  closeQuickReplies()
  closeMentions()
  selectedMentions.value = []
  selectedContactReferences.value = []
  nextTick(() => {
    resizeTextarea()
    textarea.value?.focus()
    if (!trigger) return
    const cursor = trigger.start + reply.content.length
    textarea.value?.setSelectionRange(cursor, cursor)
  })
}

function useMention(candidate: MentionCandidate) {
  const trigger = mentionTrigger.value
  if (!trigger) return
  const label = mentionText(candidate)
  const needsTrailingSpace = !/^\s/.test(text.value.slice(trigger.end, trigger.end + 1))
  text.value = `${text.value.slice(0, trigger.start)}${label}${needsTrailingSpace ? ' ' : ''}${text.value.slice(trigger.end)}`
  if (candidate.kind === 'member') {
    if (
      !selectedMentions.value.some(
        (selected) => selected.key === candidate.key,
      )
    ) {
      selectedMentions.value = [...selectedMentions.value, candidate]
    }
  } else if (
    candidate.contact_id &&
    !selectedContactReferences.value.some(
      (selected) => selected.contact_id === candidate.contact_id,
    )
  ) {
    selectedContactReferences.value = [
      ...selectedContactReferences.value,
      candidate,
    ]
  }
  closeMentions()
  nextTick(() => {
    resizeTextarea()
    textarea.value?.focus()
    const cursor = trigger.start + label.length + (needsTrailingSpace ? 1 : 0)
    textarea.value?.setSelectionRange(cursor, cursor)
  })
}

function toggleReplies() {
  closeMentions()
  showAttachments.value = false
  showEmojis.value = false
  showContactSharePicker.value = false
  if (showReplies.value && quickReplyMode.value === 'button') {
    closeQuickReplies()
    return
  }
  showReplies.value = true
  quickReplyMode.value = 'button'
  quickReplyTrigger.value = null
  quickReplyActiveIndex.value = 0
  void ensureQuickRepliesLoaded()
}

function toggleEmojis() {
  closeQuickReplies()
  closeMentions()
  showAttachments.value = false
  showContactSharePicker.value = false
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

function openContactSharePicker() {
  closeQuickReplies()
  closeMentions()
  showEmojis.value = false
  showAttachments.value = false
  showContactSharePicker.value = true
}

function selectSharedContact(contact: ContactSearchResult) {
  clearAttachments()
  selectedSharedContact.value = contact
  showContactSharePicker.value = false
}

function handlePaste(event: ClipboardEvent) {
  if (isDisabled.value || props.sending) return
  const files = Array.from(event.clipboardData?.files || [])
  if (!files.length) return
  event.preventDefault()
  addFiles(files)
}

function handleTextInput() {
  resizeTextarea()
  updateQuickReplyTrigger()
  updateMentionTrigger()
}

function handleTextareaNavigation(event?: Event) {
  if (
    event instanceof KeyboardEvent &&
    ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)
  ) {
    return
  }
  nextTick(() => {
    updateQuickReplyTrigger()
    updateMentionTrigger()
  })
}

function handleTextareaKeydown(event: KeyboardEvent) {
  if (showMentions.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeMentions()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (mentionCandidates.value.length) {
        mentionActiveIndex.value =
          (mentionActiveIndex.value + 1) % mentionCandidates.value.length
      }
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (mentionCandidates.value.length) {
        mentionActiveIndex.value =
          (mentionActiveIndex.value - 1 + mentionCandidates.value.length) %
          mentionCandidates.value.length
      }
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      const member = mentionCandidates.value[mentionActiveIndex.value]
      if (member) useMention(member)
      return
    }
  }

  if (showReplies.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeQuickReplies()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (filteredQuickReplies.value.length) {
        quickReplyActiveIndex.value =
          (quickReplyActiveIndex.value + 1) % filteredQuickReplies.value.length
      }
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (filteredQuickReplies.value.length) {
        quickReplyActiveIndex.value =
          (quickReplyActiveIndex.value - 1 + filteredQuickReplies.value.length) %
          filteredQuickReplies.value.length
      }
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      const reply = filteredQuickReplies.value[quickReplyActiveIndex.value]
      if (reply) useReply(reply)
      return
    }
  }

  if (event.key === 'Escape') {
    if (props.replyTo) {
      event.preventDefault()
      emit('cancelReply')
      return
    }
    if (showEmojis.value || showAttachments.value || showContactSharePicker.value) {
      event.preventDefault()
      showEmojis.value = false
      showAttachments.value = false
      showContactSharePicker.value = false
      return
    }
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
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
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length) addFiles(files)
}
</script>

<template>
  <div
    class="relative border-t border-line bg-panel-muted px-3 py-2.5 sm:px-4"
    @dragenter.prevent="handleDragEnter"
    @dragover.prevent
    @dragleave.prevent="handleDragLeave"
    @drop.prevent="handleDrop"
  >
    <div
      v-if="dragActive"
      class="pointer-events-none absolute inset-2 z-30 grid place-items-center rounded-lg border-2 border-dashed border-fluvius-500 bg-success-soft/95 text-center shadow-lg backdrop-blur-sm"
    >
      <div>
        <UploadCloud class="mx-auto h-8 w-8 text-fluvius-700" />
        <p class="mt-2 text-sm font-semibold text-success-strong">Solte para anexar</p>
        <p class="mt-0.5 text-xs text-success-strong">Até 10 arquivos · 25 MB por item</p>
      </div>
    </div>
    <p v-if="disabledReason" class="mx-auto mb-2.5 max-w-5xl rounded-lg bg-warning-soft px-3 py-2 text-center text-xs text-warning-strong ring-1 ring-warning/20">
      {{ disabledReason }}
    </p>
    <p v-else-if="sendError || fileError" class="mx-auto mb-2.5 max-w-5xl rounded-lg bg-danger-soft px-3 py-2 text-center text-xs text-danger-strong ring-1 ring-danger/20">
      {{ fileError || sendError }}
    </p>
    <div
      v-if="replyTo"
      class="mx-auto mb-2 flex max-w-5xl items-center gap-3 rounded-lg border-l-4 border-fluvius-600 bg-panel px-3 py-2 shadow-sm"
    >
      <Reply class="h-4 w-4 shrink-0 text-fluvius-600" />
      <div class="min-w-0 flex-1">
        <p class="text-xs font-semibold text-fluvius-700">
          Respondendo a {{ replyTo.direction === 'incoming' ? 'Cliente' : 'Você' }}
        </p>
        <p class="mt-0.5 truncate text-xs text-ink-muted">
          {{ replyTo.body || `[${replyTo.message_type}]` }}
        </p>
      </div>
      <button
        type="button"
        class="rounded-full p-1.5 text-ink-muted hover:bg-canvas"
        title="Cancelar resposta"
        @click="emit('cancelReply')"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
    <div
      v-if="selectedSharedContact"
      class="mx-auto mb-2 flex h-[68px] max-w-5xl items-center gap-3 rounded-lg bg-panel px-3 shadow-sm ring-1 ring-black/5"
    >
      <span class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-success-soft text-success-strong">
        <UserRound class="h-5 w-5" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-sm font-semibold text-ink">
          {{ selectedSharedContact.display_name }}
        </span>
        <span class="mt-0.5 block truncate text-xs text-ink-muted">
          +{{ selectedSharedContact.phone_number }}
        </span>
      </span>
      <button
        type="button"
        class="rounded-full p-2 text-ink-muted hover:bg-canvas"
        title="Remover contato"
        @click="selectedSharedContact = null"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
    <div
      v-if="isRecording"
      class="mx-auto mb-2 flex h-12 max-w-5xl items-center gap-3 rounded-lg bg-panel px-3 shadow-sm ring-1 ring-black/5"
    >
      <span class="h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-danger" />
      <span class="min-w-14 font-mono text-sm font-semibold text-ink">
        {{ recordingTime(recordingSeconds) }}
      </span>
      <span class="flex-1 text-xs text-ink-muted">
        {{ recordingState === 'paused' ? 'Gravação pausada' : 'Gravando áudio' }}
      </span>
      <button
        v-if="recordingState === 'recording'"
        type="button"
        class="grid h-8 w-8 place-items-center rounded-full text-ink-muted hover:bg-canvas"
        title="Pausar gravação"
        @click="pauseRecording"
      >
        <Pause class="h-4 w-4" />
      </button>
      <button
        v-else
        type="button"
        class="grid h-8 w-8 place-items-center rounded-full text-ink-muted hover:bg-canvas"
        title="Retomar gravação"
        @click="resumeRecording"
      >
        <Play class="h-4 w-4" />
      </button>
      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-full text-danger-strong hover:bg-danger-soft"
        title="Cancelar gravação"
        @click="cancelRecording"
      >
        <Trash2 class="h-4 w-4" />
      </button>
      <button
        type="button"
        class="grid h-8 w-8 place-items-center rounded-full bg-danger text-white hover:bg-danger-strong"
        title="Concluir gravação"
        @click="stopRecording"
      >
        <Square class="h-3.5 w-3.5 fill-current" />
      </button>
    </div>
    <div v-if="selectedAttachments.length" class="mx-auto mb-2 max-w-5xl">
      <div class="mb-1.5 flex items-center justify-between gap-3 px-1">
        <p class="text-[11px] font-medium text-ink-muted">
          {{ selectedAttachments.length === 1 ? '1 anexo' : `${selectedAttachments.length} anexos` }}
          <span v-if="selectedAttachments.length > 1">· legenda no primeiro arquivo compatível</span>
        </p>
        <button
          type="button"
          class="text-[11px] font-medium text-danger-strong hover:underline"
          @click="clearAttachments"
        >
          Remover todos
        </button>
      </div>
      <div class="soft-scrollbar flex gap-2 overflow-x-auto pb-1">
        <div
          v-for="(attachment, index) in selectedAttachments"
          :key="attachment.id"
          class="flex h-[76px] w-[260px] shrink-0 items-center gap-2 overflow-hidden rounded-lg bg-panel p-2 shadow-sm ring-1 ring-black/5"
        >
          <div class="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-md bg-fluvius-50 text-fluvius-700">
            <img
              v-if="(attachment.kind === 'image' || attachment.kind === 'sticker') && attachment.previewUrl"
              :src="attachment.previewUrl"
              :alt="attachment.file.name"
              class="h-full w-full object-cover"
            />
            <video
              v-else-if="attachment.kind === 'video' && attachment.previewUrl"
              :src="attachment.previewUrl"
              class="h-full w-full object-cover"
              muted
            />
            <Music v-else-if="attachment.kind === 'audio'" class="h-5 w-5" />
            <Sticker v-else-if="attachment.kind === 'sticker'" class="h-5 w-5" />
            <Film v-else-if="attachment.kind === 'video'" class="h-5 w-5" />
            <ImageIcon v-else-if="attachment.kind === 'image'" class="h-5 w-5" />
            <FileText v-else class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-xs font-semibold text-ink">
              {{ attachment.file.name || 'Arquivo colado' }}
            </p>
            <p class="mt-1 text-[10px] uppercase text-ink-muted">
              {{ attachmentKindLabel(attachment.kind) }} · {{ fileSize(attachment.file.size) }}
            </p>
            <div v-if="selectedAttachments.length > 1" class="mt-1 flex gap-0.5">
              <button
                type="button"
                class="rounded p-0.5 text-ink-muted hover:bg-canvas disabled:opacity-30"
                :disabled="index === 0"
                title="Mover para a esquerda"
                @click="moveAttachment(index, -1)"
              >
                <ArrowLeft class="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                class="rounded p-0.5 text-ink-muted hover:bg-canvas disabled:opacity-30"
                :disabled="index === selectedAttachments.length - 1"
                title="Mover para a direita"
                @click="moveAttachment(index, 1)"
              >
                <ArrowRight class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <button
            type="button"
            class="self-start rounded-full p-1 text-ink-muted transition hover:bg-canvas"
            title="Remover anexo"
            @click="removeAttachment(attachment.id)"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
    <AudioMessagePlayer
      v-if="selectedAttachments.length === 1 && selectedAttachments[0].kind === 'audio' && selectedAttachments[0].previewUrl"
      class="mx-auto mb-2"
      :src="selectedAttachments[0].previewUrl || ''"
      :file-name="selectedAttachments[0].file.name || 'Áudio selecionado'"
    />
    <form class="mx-auto flex max-w-5xl items-end gap-2" @submit.prevent="submit">
      <div class="relative">
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-ink-secondary transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
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
          class="grid h-11 w-11 place-items-center rounded-full text-ink-secondary transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
          :class="{ 'bg-black/5 text-fluvius-700': showReplies }"
          :disabled="isDisabled"
          title="Respostas rápidas"
          @click="toggleReplies"
        >
          <Zap class="h-5 w-5" />
        </button>
        <div
          v-if="showReplies"
          class="fixed inset-0 z-20"
          aria-hidden="true"
          @click="closeQuickReplies"
        />
        <QuickReplyPicker
          v-if="showReplies"
          :active-index="quickReplyActiveIndex"
          :error="quickRepliesError"
          :loading="quickRepliesLoading"
          :query="quickReplyQuery"
          :replies="filteredQuickReplies"
          @hover="quickReplyActiveIndex = $event"
          @select="useReply"
        />
      </div>
      <div class="relative">
        <input
          ref="fileInput"
          class="hidden"
          type="file"
          :accept="attachmentAccept"
          :multiple="attachmentMode !== 'sticker'"
          @change="selectFile"
        />
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full text-ink-secondary transition hover:bg-black/5 hover:text-fluvius-700 disabled:opacity-40"
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
          class="absolute bottom-14 left-0 z-30 w-60 overflow-hidden rounded-lg bg-panel py-2 text-ink shadow-2xl ring-1 ring-black/5"
        >
          <p class="px-4 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
            Enviar anexo
          </p>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-panel-muted"
            @click="openAttachmentPicker('media', 'image/*,video/*')"
          >
            <span class="grid h-9 w-9 place-items-center rounded-full bg-violet-500 text-white">
              <ImageIcon class="h-5 w-5" />
            </span>
            <span>
              <span class="block font-medium">Fotos e vídeos</span>
              <span class="block text-[10px] text-ink-faint">JPG, PNG, GIF, MP4, MOV e WebM</span>
            </span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-panel-muted"
            @click="openContactSharePicker"
          >
            <span class="grid h-9 w-9 place-items-center rounded-full bg-emerald-600 text-white">
              <UserRound class="h-5 w-5" />
            </span>
            <span>
              <span class="block font-medium">Contato</span>
              <span class="block text-[10px] text-ink-faint">Compartilhar cartão do WhatsApp</span>
            </span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-panel-muted"
            @click="
              openAttachmentPicker(
                'document',
                '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.html,.htm,.json,.xml,.txt,.csv,.zip',
              )
            "
          >
            <span class="grid h-9 w-9 place-items-center rounded-full bg-sky-500 text-white">
              <FileText class="h-5 w-5" />
            </span>
            <span>
              <span class="block font-medium">Documentos</span>
              <span class="block text-[10px] text-ink-faint">PDF, Office, HTML, JSON, XML, texto e ZIP</span>
            </span>
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-panel-muted"
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
              <span class="block text-[10px] text-ink-faint">AAC, MP3, OGG, WAV e outros</span>
            </span>
          </button>
        </div>
        <div
          v-if="showContactSharePicker"
          class="fixed inset-0 z-20"
          aria-hidden="true"
          @click="showContactSharePicker = false"
        />
        <ContactSharePicker
          v-if="showContactSharePicker"
          @select="selectSharedContact"
        />
      </div>
      <button
        type="button"
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full text-ink-secondary transition hover:bg-black/5 hover:text-success disabled:opacity-40"
        :disabled="isDisabled || sending || preparingSticker"
        :title="preparingSticker ? 'Preparando figurinha...' : 'Enviar figurinha'"
        @click="openStickerPicker"
      >
        <span
          v-if="preparingSticker"
          class="h-4 w-4 animate-spin rounded-full border-2 border-line-strong border-t-ink-secondary"
        />
        <Sticker v-else class="h-5 w-5" />
      </button>
      <div class="relative flex-1">
        <div
          v-if="showMentions"
          class="fixed inset-0 z-20"
          aria-hidden="true"
          @click="closeMentions"
        />
        <GroupMentionPicker
          v-if="showMentions"
          :active-index="mentionActiveIndex"
          :candidates="mentionCandidates"
          :loading="groupMembersLoading || contactSearchLoading"
          :error="contactSearchError"
          :query="mentionQuery"
          @hover="mentionActiveIndex = $event"
          @select="useMention"
        />
        <textarea
          ref="textarea"
          v-model="text"
          rows="1"
          class="soft-scrollbar min-h-11 w-full resize-none rounded-lg border-0 bg-panel px-4 py-3 text-[13.5px] leading-5 text-ink shadow-sm outline-none placeholder:text-ink-muted focus:ring-1 focus:ring-fluvius-500/30 disabled:bg-panel-muted"
          placeholder="Digite uma mensagem..."
          :disabled="isDisabled"
          @click="handleTextareaNavigation"
          @focus="handleTextareaNavigation"
          @input="handleTextInput"
          @keydown="handleTextareaKeydown"
          @keyup="handleTextareaNavigation"
          @paste="handlePaste"
        />
      </div>
      <button
        :type="hasSendContent ? 'submit' : 'button'"
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-fluvius-600 text-white shadow-sm transition hover:bg-fluvius-700 disabled:cursor-not-allowed disabled:bg-disabled disabled:shadow-none"
        :disabled="
          isDisabled ||
          sending ||
          preparingSticker ||
          isRecording
        "
        :title="
          preparingSticker
            ? 'Preparando figurinha...'
            : sending
              ? 'Enviando...'
              : hasSendContent
                ? 'Enviar'
                : 'Gravar áudio'
        "
        @click="!hasSendContent && startRecording()"
      >
        <span
          v-if="sending || preparingSticker"
          class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
        />
        <Send v-else-if="hasSendContent" class="h-5 w-5" />
        <Mic v-else class="h-5 w-5" />
      </button>
    </form>
  </div>
</template>
