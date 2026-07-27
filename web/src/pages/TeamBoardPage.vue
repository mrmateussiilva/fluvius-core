<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Columns3,
  GripVertical,
  Inbox,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  UserRound,
  WifiOff,
  X,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import {
  assignConversation,
  releaseConversation,
} from '../api/conversations'
import type {
  ActiveTenantUser,
  Conversation,
  MessageType,
} from '../api/types'
import { listActiveUsers } from '../api/users'
import { useAuthStore } from '../stores/authStore'
import { useConversationStore } from '../stores/conversationStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const WAITING_COLUMN_ID = 'waiting'

interface BoardColumn {
  id: string
  name: string
  role: ActiveTenantUser['role'] | null
}

const auth = useAuthStore()
const conversations = useConversationStore()
const realtime = useRealtimeStore()
const router = useRouter()
const members = ref<ActiveTenantUser[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const operationError = ref('')
const search = ref('')
const movingConversationIds = ref<string[]>([])
const draggedConversationId = ref<string | null>(null)
const dragOverColumnId = ref<string | null>(null)

const isAdmin = computed(() => auth.user?.role === 'admin')
const columns = computed<BoardColumn[]>(() => [
  {
    id: WAITING_COLUMN_ID,
    name: 'Aguardando',
    role: null,
  },
  ...members.value.map((member) => ({
    id: member.id,
    name: member.name,
    role: member.role,
  })),
])
const operationalConversations = computed(() =>
  conversations.conversations.filter(
    (conversation) => conversation.status !== 'closed',
  ),
)
const filteredConversations = computed(() => {
  const query = search.value.trim().toLocaleLowerCase('pt-BR')
  if (!query) return operationalConversations.value
  return operationalConversations.value.filter((conversation) =>
    [
      conversation.contact_name,
      conversation.contact_phone,
      conversation.last_message_body,
    ].some((value) => value?.toLocaleLowerCase('pt-BR').includes(query)),
  )
})
const waitingCount = computed(
  () =>
    operationalConversations.value.filter(
      (conversation) =>
        conversation.status === 'new' || !conversation.assigned_user_id,
    ).length,
)
const activeCount = computed(
  () =>
    operationalConversations.value.filter(
      (conversation) =>
        conversation.status === 'open' &&
        Boolean(conversation.assigned_user_id),
    ).length,
)

function cardsForColumn(columnId: string) {
  if (columnId === WAITING_COLUMN_ID) {
    return filteredConversations.value.filter(
      (conversation) =>
        conversation.status === 'new' || !conversation.assigned_user_id,
    )
  }
  return filteredConversations.value.filter(
    (conversation) =>
      conversation.status === 'open' &&
      conversation.assigned_user_id === columnId,
  )
}

function unreadForColumn(columnId: string) {
  return cardsForColumn(columnId).reduce(
    (total, conversation) => total + conversation.unread_count,
    0,
  )
}

function initials(value: string) {
  return value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

function contactName(conversation: Conversation) {
  return conversation.contact_name || conversation.contact_phone
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
    (conversation.last_message_type
      ? typeLabels[conversation.last_message_type]
      : 'Sem mensagens')
  return conversation.last_message_direction === 'outgoing'
    ? `Equipe: ${content}`
    : content
}

function timeLabel(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const messageDay = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  )
  const difference = Math.round(
    (today.getTime() - messageDay.getTime()) / 86_400_000,
  )
  if (difference === 0) {
    return new Intl.DateTimeFormat('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  }
  if (difference === 1) return 'Ontem'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
  }).format(date)
}

function assignmentValue(conversation: Conversation) {
  return conversation.status === 'open' && conversation.assigned_user_id
    ? conversation.assigned_user_id
    : WAITING_COLUMN_ID
}

function isMoving(conversationId: string) {
  return movingConversationIds.value.includes(conversationId)
}

async function loadBoard(showFullLoading = false) {
  if (showFullLoading) loading.value = true
  else refreshing.value = true
  error.value = ''
  try {
    const [, activeMembers] = await Promise.all([
      conversations.loadConversations(),
      listActiveUsers(),
    ])
    members.value = activeMembers
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar o quadro da equipe'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function moveConversation(
  conversationId: string,
  destinationColumnId: string,
) {
  if (!isAdmin.value || isMoving(conversationId)) return
  const conversation = conversations.conversations.find(
    (item) => item.id === conversationId,
  )
  if (!conversation) return
  if (
    destinationColumnId === WAITING_COLUMN_ID &&
    (conversation.status !== 'open' || !conversation.assigned_user_id)
  ) {
    return
  }
  if (
    destinationColumnId !== WAITING_COLUMN_ID &&
    conversation.status === 'open' &&
    conversation.assigned_user_id === destinationColumnId
  ) {
    return
  }

  movingConversationIds.value.push(conversationId)
  operationError.value = ''
  try {
    const updated =
      destinationColumnId === WAITING_COLUMN_ID
        ? await releaseConversation(conversationId)
        : await assignConversation(conversationId, destinationColumnId)
    conversations.replace(updated)
  } catch (exception) {
    operationError.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível mover o atendimento'
    await conversations.loadConversations()
  } finally {
    movingConversationIds.value = movingConversationIds.value.filter(
      (id) => id !== conversationId,
    )
  }
}

function startDrag(event: DragEvent, conversation: Conversation) {
  if (!isAdmin.value || isMoving(conversation.id)) {
    event.preventDefault()
    return
  }
  draggedConversationId.value = conversation.id
  event.dataTransfer?.setData('text/plain', conversation.id)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function endDrag() {
  draggedConversationId.value = null
  dragOverColumnId.value = null
}

function dragOver(columnId: string) {
  if (isAdmin.value && draggedConversationId.value) {
    dragOverColumnId.value = columnId
  }
}

async function dropOnColumn(event: DragEvent, columnId: string) {
  event.preventDefault()
  const conversationId =
    draggedConversationId.value ||
    event.dataTransfer?.getData('text/plain') ||
    null
  endDrag()
  if (conversationId) await moveConversation(conversationId, columnId)
}

async function selectAssignment(
  event: Event,
  conversation: Conversation,
) {
  const select = event.target as HTMLSelectElement
  await moveConversation(conversation.id, select.value)
}

async function openConversation(conversationId: string) {
  conversations.selectedId = conversationId
  await router.push({
    path: '/app/conversations',
    query: { conversation: conversationId },
  })
}

function refreshWhenVisible() {
  if (document.visibilityState === 'visible') void loadBoard()
}

onMounted(async () => {
  await auth.restore()
  await loadBoard(true)
  realtime.connect()
  document.addEventListener('visibilitychange', refreshWhenVisible)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', refreshWhenVisible)
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-[#eef1f3]">
    <header class="shrink-0 border-b border-slate-200 bg-white px-4 py-4 sm:px-6">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div class="flex items-center gap-2 text-fluvius-700">
            <Columns3 class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Operação em tempo real
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight text-slate-900">
            Quadro da equipe
          </h1>
          <p class="mt-1 text-sm text-slate-500">
            Veja quem está atendendo cada conversa e como a fila está distribuída.
          </p>
        </div>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div class="flex items-center gap-2 text-xs">
            <span class="rounded-full bg-amber-50 px-2.5 py-1.5 font-medium text-amber-700 ring-1 ring-amber-100">
              {{ waitingCount }} aguardando
            </span>
            <span class="rounded-full bg-emerald-50 px-2.5 py-1.5 font-medium text-emerald-700 ring-1 ring-emerald-100">
              {{ activeCount }} em atendimento
            </span>
          </div>
          <label class="flex h-10 min-w-0 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 text-slate-500 focus-within:bg-white focus-within:ring-2 focus-within:ring-fluvius-500/15 sm:w-72">
            <Search class="h-4 w-4 shrink-0" />
            <input
              v-model="search"
              type="search"
              placeholder="Buscar contato ou mensagem"
              class="min-w-0 flex-1 bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400"
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
          <button
            type="button"
            class="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
            :disabled="refreshing"
            title="Atualizar quadro"
            @click="loadBoard()"
          >
            <RefreshCw
              class="h-4 w-4"
              :class="refreshing ? 'animate-spin' : ''"
            />
          </button>
        </div>
      </div>
      <div
        class="mt-3 flex items-center gap-2 rounded-xl px-3 py-2 text-xs"
        :class="
          isAdmin
            ? 'bg-fluvius-50 text-fluvius-800'
            : 'bg-slate-100 text-slate-600'
        "
      >
        <ShieldCheck v-if="isAdmin" class="h-4 w-4 shrink-0" />
        <UserRound v-else class="h-4 w-4 shrink-0" />
        <span v-if="isAdmin">
          Arraste os cards entre as colunas ou use o seletor para redistribuir.
        </span>
        <span v-else>
          Visualização da equipe. Somente administradores podem redistribuir atendimentos.
        </span>
      </div>
    </header>

    <div
      v-if="error || operationError"
      class="shrink-0 border-b border-rose-100 bg-rose-50 px-4 py-2 text-center text-xs text-rose-700"
    >
      {{ operationError || error }}
    </div>

    <div
      v-if="loading"
      class="grid min-h-0 flex-1 place-items-center text-sm text-slate-500"
    >
      <div class="flex items-center gap-2">
        <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
        Carregando distribuição dos atendimentos...
      </div>
    </div>

    <div
      v-else
      class="soft-scrollbar min-h-0 flex-1 overflow-x-auto overflow-y-hidden p-4 sm:p-5"
    >
      <div class="flex h-full min-w-max items-start gap-4">
        <section
          v-for="column in columns"
          :key="column.id"
          class="flex max-h-full w-[290px] shrink-0 flex-col rounded-2xl border bg-slate-100/80 shadow-sm transition sm:w-[310px]"
          :class="
            dragOverColumnId === column.id
              ? 'border-fluvius-400 bg-fluvius-50 ring-2 ring-fluvius-400/20'
              : 'border-slate-200'
          "
          @dragenter.prevent="dragOver(column.id)"
          @dragover.prevent="dragOver(column.id)"
          @dragleave.self="dragOverColumnId = null"
          @drop="dropOnColumn($event, column.id)"
        >
          <header class="flex items-center gap-3 border-b border-slate-200/80 px-3.5 py-3">
            <div
              class="grid h-9 w-9 shrink-0 place-items-center rounded-xl text-xs font-semibold"
              :class="
                column.id === WAITING_COLUMN_ID
                  ? 'bg-amber-100 text-amber-700'
                  : 'bg-white text-fluvius-700 ring-1 ring-slate-200'
              "
            >
              <Inbox
                v-if="column.id === WAITING_COLUMN_ID"
                class="h-4 w-4"
              />
              <span v-else>{{ initials(column.name) }}</span>
            </div>
            <div class="min-w-0 flex-1">
              <h2 class="truncate text-sm font-semibold text-slate-900">
                {{ column.name }}
              </h2>
              <p class="text-[10px] uppercase tracking-wide text-slate-500">
                {{
                  column.id === WAITING_COLUMN_ID
                    ? 'Sem responsável'
                    : column.role === 'admin'
                      ? 'Administrador'
                      : 'Atendente'
                }}
              </p>
            </div>
            <div class="flex items-center gap-1.5">
              <span
                v-if="unreadForColumn(column.id)"
                class="rounded-full bg-fluvius-600 px-1.5 py-0.5 text-[9px] font-semibold text-white"
                :title="`${unreadForColumn(column.id)} mensagens não lidas`"
              >
                {{ unreadForColumn(column.id) > 99 ? '99+' : unreadForColumn(column.id) }}
              </span>
              <span class="min-w-6 rounded-full bg-white px-1.5 text-center text-[10px] font-semibold leading-6 text-slate-600 ring-1 ring-slate-200">
                {{ cardsForColumn(column.id).length }}
              </span>
            </div>
          </header>

          <div class="soft-scrollbar min-h-20 flex-1 space-y-2.5 overflow-y-auto p-2.5">
            <article
              v-for="conversation in cardsForColumn(column.id)"
              :key="conversation.id"
              class="group rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition hover:-translate-y-px hover:border-slate-300 hover:shadow-md"
              :class="[
                isAdmin ? 'cursor-grab active:cursor-grabbing' : '',
                draggedConversationId === conversation.id ? 'opacity-45' : '',
                isMoving(conversation.id) ? 'pointer-events-none opacity-60' : '',
              ]"
              :draggable="isAdmin && !isMoving(conversation.id)"
              @dragstart="startDrag($event, conversation)"
              @dragend="endDrag"
            >
              <div class="flex items-start gap-2.5">
                <GripVertical
                  v-if="isAdmin"
                  class="mt-0.5 h-4 w-4 shrink-0 text-slate-300 transition group-hover:text-slate-500"
                />
                <button
                  type="button"
                  class="min-w-0 flex-1 text-left"
                  @click="openConversation(conversation.id)"
                >
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                      <h3 class="truncate text-sm font-semibold text-slate-900">
                        {{ contactName(conversation) }}
                      </h3>
                      <p class="mt-0.5 truncate text-[11px] text-slate-500">
                        {{ conversation.contact_phone }}
                      </p>
                    </div>
                    <time
                      class="shrink-0 text-[10px] text-slate-400"
                      :datetime="conversation.last_message_at || undefined"
                    >
                      {{ timeLabel(conversation.last_message_at) }}
                    </time>
                  </div>
                  <p class="mt-2 line-clamp-2 min-h-8 text-xs leading-4 text-slate-600">
                    {{ messagePreview(conversation) }}
                  </p>
                </button>
              </div>

              <div class="mt-3 flex items-center gap-2 border-t border-slate-100 pt-2.5">
                <span
                  v-if="conversation.unread_count"
                  class="rounded-full bg-fluvius-50 px-2 py-1 text-[10px] font-semibold text-fluvius-700"
                >
                  {{ conversation.unread_count > 99 ? '99+' : conversation.unread_count }} novas
                </span>
                <span
                  v-if="conversation.channel_status !== 'connected'"
                  class="flex items-center gap-1 rounded-full bg-rose-50 px-2 py-1 text-[10px] font-medium text-rose-700"
                >
                  <WifiOff class="h-3 w-3" />
                  Canal offline
                </span>
                <button
                  v-if="!conversation.unread_count && conversation.channel_status === 'connected'"
                  type="button"
                  class="flex items-center gap-1 text-[10px] font-medium text-slate-500 transition hover:text-fluvius-700"
                  @click="openConversation(conversation.id)"
                >
                  <MessageCircle class="h-3 w-3" />
                  Abrir conversa
                </button>
                <LoaderCircle
                  v-if="isMoving(conversation.id)"
                  class="ml-auto h-4 w-4 animate-spin text-fluvius-700"
                />
              </div>

              <label
                v-if="isAdmin"
                class="mt-2.5 block"
                @click.stop
                @mousedown.stop
              >
                <span class="sr-only">Mover atendimento</span>
                <select
                  class="h-8 w-full rounded-lg border border-slate-200 bg-slate-50 px-2 text-[11px] text-slate-700 outline-none transition hover:bg-white focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
                  :value="assignmentValue(conversation)"
                  :disabled="isMoving(conversation.id)"
                  @change="selectAssignment($event, conversation)"
                >
                  <option :value="WAITING_COLUMN_ID">Aguardando</option>
                  <option
                    v-for="member in members"
                    :key="member.id"
                    :value="member.id"
                  >
                    {{ member.name }}
                  </option>
                </select>
              </label>
            </article>

            <div
              v-if="!cardsForColumn(column.id).length"
              class="grid min-h-28 place-items-center rounded-xl border border-dashed border-slate-300 bg-white/40 px-4 text-center"
            >
              <div>
                <Inbox class="mx-auto h-5 w-5 text-slate-300" />
                <p class="mt-2 text-xs text-slate-400">
                  {{
                    search
                      ? 'Nenhuma conversa encontrada'
                      : column.id === WAITING_COLUMN_ID
                        ? 'Fila livre'
                        : 'Sem atendimentos'
                  }}
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
