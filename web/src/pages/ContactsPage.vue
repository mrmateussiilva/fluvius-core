<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  LoaderCircle,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  UserRoundPlus,
  X,
} from 'lucide-vue-next'
import { listChannels } from '../api/channels'
import {
  createContact,
  listContacts,
  startContactConversation,
  updateContact,
} from '../api/contacts'
import { createSyncRun, getSyncRun, listSyncRuns } from '../api/sync'
import type { Channel, ContactListItem, SyncRun } from '../api/types'
import { useAuthStore } from '../stores/authStore'

const PAGE_SIZE = 30
const SYNC_POLL_INTERVAL = 2_500

const router = useRouter()
const auth = useAuthStore()
const contacts = ref<ContactListItem[]>([])
const channels = ref<Channel[]>([])
const search = ref('')
const appliedSearch = ref('')
const total = ref(0)
const offset = ref(0)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const showCreateForm = ref(false)
const selectedChannelId = ref('')
const startingContactId = ref<string | null>(null)
const editingContactId = ref<string | null>(null)
const editingName = ref('')
const syncingContacts = ref(false)
const activeSyncRunId = ref<string | null>(null)
let syncPollTimer: number | null = null
const form = reactive({
  name: '',
  phone_number: '',
})

const connectedChannels = computed(() =>
  channels.value.filter((channel) => channel.status === 'connected'),
)
const hasPreviousPage = computed(() => offset.value > 0)
const hasNextPage = computed(() => offset.value + PAGE_SIZE < total.value)
const canSyncContacts = computed(() => auth.user?.role === 'admin')

function applyChannelDefault() {
  if (
    selectedChannelId.value &&
    connectedChannels.value.some((channel) => channel.id === selectedChannelId.value)
  ) {
    return
  }
  selectedChannelId.value = connectedChannels.value[0]?.id || ''
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const response = await listContacts({
      q: appliedSearch.value,
      limit: PAGE_SIZE,
      offset: offset.value,
    })
    contacts.value = response.items
    total.value = response.total
  } catch (exception) {
    error.value =
      exception instanceof Error ? exception.message : 'Não foi possível carregar contatos'
  } finally {
    loading.value = false
  }
}

async function loadChannels() {
  channels.value = await listChannels()
  applyChannelDefault()
}

function clearSyncPoll() {
  if (syncPollTimer !== null) window.clearTimeout(syncPollTimer)
  syncPollTimer = null
}

function syncProgressNotice(run: SyncRun) {
  if (run.status === 'queued') return 'Sincronização de contatos na fila.'
  if (run.total_items > 0) {
    return `Sincronizando contatos: ${run.processed_items} de ${run.total_items}.`
  }
  return 'Sincronizando contatos...'
}

function syncedItemLabel(count: number) {
  return `${count} item${count === 1 ? '' : 's'} atualizado${count === 1 ? '' : 's'}`
}

async function pollContactSync() {
  const runId = activeSyncRunId.value
  if (!runId) return
  try {
    const run = await getSyncRun(runId)
    if (run.status === 'queued' || run.status === 'running') {
      notice.value = syncProgressNotice(run)
      clearSyncPoll()
      syncPollTimer = window.setTimeout(pollContactSync, SYNC_POLL_INTERVAL)
      return
    }

    activeSyncRunId.value = null
    syncingContacts.value = false
    clearSyncPoll()
    if (run.status === 'completed') {
      notice.value = `Sincronização concluída: ${syncedItemLabel(run.succeeded_items)}.`
      await refresh()
      return
    }
    if (run.status === 'partial') {
      notice.value = `Sincronização parcial: ${syncedItemLabel(run.succeeded_items)} e ${run.failed_items} com falha.`
      await refresh()
      return
    }
    error.value = run.error || 'A sincronização de contatos falhou.'
  } catch (exception) {
    activeSyncRunId.value = null
    syncingContacts.value = false
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível acompanhar a sincronização de contatos'
  }
}

async function syncContacts() {
  if (!canSyncContacts.value || !selectedChannelId.value || syncingContacts.value) return
  syncingContacts.value = true
  error.value = ''
  notice.value = ''
  try {
    const runs = await listSyncRuns(selectedChannelId.value)
    const activeRun = runs.find(
      (run) =>
        (run.sync_type === 'contacts' || run.sync_type === 'all') &&
        (run.status === 'queued' || run.status === 'running'),
    )
    const run =
      activeRun ||
      (await createSyncRun({
        channel_id: selectedChannelId.value,
        sync_type: 'contacts',
        recent_days: 7,
      }))
    activeSyncRunId.value = run.id
    notice.value = syncProgressNotice(run)
    clearSyncPoll()
    syncPollTimer = window.setTimeout(pollContactSync, SYNC_POLL_INTERVAL)
  } catch (exception) {
    syncingContacts.value = false
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível iniciar a sincronização de contatos'
  }
}

async function submitSearch() {
  appliedSearch.value = search.value.trim()
  offset.value = 0
  await refresh()
}

async function clearSearch() {
  search.value = ''
  appliedSearch.value = ''
  offset.value = 0
  await refresh()
}

async function changePage(direction: -1 | 1) {
  offset.value = Math.max(0, offset.value + direction * PAGE_SIZE)
  await refresh()
}

async function submitContact() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const contact = await createContact({
      name: form.name,
      phone_number: form.phone_number,
    })
    Object.assign(form, { name: '', phone_number: '' })
    showCreateForm.value = false
    notice.value = `Contato ${contact.display_name} salvo.`
    appliedSearch.value = ''
    search.value = ''
    offset.value = 0
    await refresh()
  } catch (exception) {
    error.value =
      exception instanceof Error ? exception.message : 'Não foi possível salvar contato'
  } finally {
    saving.value = false
  }
}

function startEditing(contact: ContactListItem) {
  editingContactId.value = contact.id
  editingName.value = contact.name || contact.display_name
}

function stopEditing() {
  editingContactId.value = null
  editingName.value = ''
}

async function saveEditing(contact: ContactListItem) {
  if (!editingContactId.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const updated = await updateContact(contact.id, {
      name: editingName.value,
    })
    contacts.value = contacts.value.map((item) =>
      item.id === contact.id
        ? {
            ...item,
            name: updated.name,
            display_name: updated.display_name,
            updated_at: new Date().toISOString(),
          }
        : item,
    )
    notice.value = `Contato ${updated.display_name} atualizado.`
    stopEditing()
  } catch (exception) {
    error.value =
      exception instanceof Error ? exception.message : 'Não foi possível editar contato'
  } finally {
    saving.value = false
  }
}

async function openConversation(contact: ContactListItem) {
  if (!selectedChannelId.value || startingContactId.value) return
  startingContactId.value = contact.id
  error.value = ''
  notice.value = ''
  try {
    const conversation = await startContactConversation(
      contact.id,
      selectedChannelId.value,
    )
    await router.push({
      path: '/app/conversations',
      query: {
        channel: conversation.channel_id,
        conversation: conversation.id,
      },
    })
  } catch (exception) {
    error.value =
      exception instanceof Error ? exception.message : 'Não foi possível abrir conversa'
  } finally {
    startingContactId.value = null
  }
}

function phoneLabel(value: string) {
  if (value.length === 13 && value.startsWith('55')) {
    return `+${value.slice(0, 2)} ${value.slice(2, 4)} ${value.slice(4, 9)}-${value.slice(9)}`
  }
  if (value.length === 12 && value.startsWith('55')) {
    return `+${value.slice(0, 2)} ${value.slice(2, 4)} ${value.slice(4, 8)}-${value.slice(8)}`
  }
  return value
}

function dateLabel(value: string | null) {
  if (!value) return 'Sem conversa'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(async () => {
  try {
    await auth.restore()
    await Promise.all([loadChannels(), refresh()])
  } catch (exception) {
    error.value =
      exception instanceof Error ? exception.message : 'Não foi possível carregar contatos'
  }
})

onBeforeUnmount(clearSyncPoll)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-canvas">
    <header class="shrink-0 border-b border-line bg-panel px-5 py-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-fluvius-700">Atendimento</p>
          <h1 class="mt-0.5 text-xl font-semibold tracking-tight text-ink">Contatos</h1>
        </div>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <form class="flex h-10 min-w-0 items-center gap-2 rounded-lg border border-line bg-canvas px-3 text-ink-secondary focus-within:bg-panel focus-within:ring-1 focus-within:ring-fluvius-500/30 sm:w-80" @submit.prevent="submitSearch">
            <Search class="h-4 w-4 shrink-0" />
            <input
              v-model="search"
              type="search"
              placeholder="Buscar nome ou telefone"
              class="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-muted"
            />
            <button
              v-if="search || appliedSearch"
              type="button"
              class="rounded-md p-1 hover:bg-line"
              title="Limpar busca"
              @click="clearSearch"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </form>
          <button
            v-if="canSyncContacts"
            type="button"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!selectedChannelId || syncingContacts"
            title="Sincronizar contatos do canal selecionado"
            @click="syncContacts"
          >
            <RefreshCw class="h-4 w-4" :class="syncingContacts ? 'animate-spin' : ''" />
            {{ syncingContacts ? 'Sincronizando' : 'Sincronizar contatos' }}
          </button>
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-neutral-action px-3 text-sm font-medium text-white transition hover:bg-neutral-action"
            @click="showCreateForm = !showCreateForm"
          >
            <Plus class="h-4 w-4" />
            Novo
          </button>
        </div>
      </div>
    </header>

    <section class="shrink-0 border-b border-line bg-panel px-5 py-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <label class="flex min-w-0 items-center gap-2 text-sm text-ink-secondary">
          <MessageCircle class="h-4 w-4 shrink-0 text-fluvius-700" />
          <select
            v-model="selectedChannelId"
            class="h-9 min-w-0 rounded-lg border border-line bg-panel px-3 text-[13px] font-medium text-ink outline-none focus:ring-1 focus:ring-fluvius-500/30"
            aria-label="Canal para iniciar conversa"
            :disabled="!connectedChannels.length || syncingContacts"
          >
            <option value="" disabled>Canal conectado</option>
            <option
              v-for="channel in connectedChannels"
              :key="channel.id"
              :value="channel.id"
            >
              {{ channel.name }}{{ channel.phone_number ? ` · ${channel.phone_number}` : '' }}
            </option>
          </select>
        </label>
        <p
          v-if="error"
          class="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger-strong"
        >
          {{ error }}
        </p>
        <p
          v-else-if="notice"
          class="rounded-lg border border-success/30 bg-success-soft px-3 py-2 text-sm text-success-strong"
        >
          {{ notice }}
        </p>
      </div>
    </section>

    <form
      v-if="showCreateForm"
      class="grid shrink-0 gap-3 border-b border-line bg-panel px-5 py-4 md:grid-cols-[minmax(0,1fr)_220px_auto]"
      @submit.prevent="submitContact"
    >
      <input
        v-model="form.name"
        required
        maxlength="160"
        placeholder="Nome"
        class="h-10 rounded-lg border border-line bg-panel px-3 text-sm text-ink outline-none placeholder:text-ink-faint focus:ring-1 focus:ring-fluvius-500/30"
      />
      <input
        v-model="form.phone_number"
        required
        maxlength="32"
        placeholder="+55 27 99999-9999"
        class="h-10 rounded-lg border border-line bg-panel px-3 text-sm text-ink outline-none placeholder:text-ink-faint focus:ring-1 focus:ring-fluvius-500/30"
      />
      <button
        type="submit"
        class="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 text-sm font-medium text-white transition hover:bg-fluvius-800 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="saving"
      >
        <LoaderCircle v-if="saving" class="h-4 w-4 animate-spin" />
        <UserRoundPlus v-else class="h-4 w-4" />
        Salvar
      </button>
    </form>

    <div class="soft-scrollbar min-h-0 flex-1 overflow-auto">
      <table class="min-w-full border-separate border-spacing-0 bg-panel text-left text-sm">
        <thead class="sticky top-0 z-10 bg-canvas text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
          <tr>
            <th class="border-b border-line px-5 py-3">Nome</th>
            <th class="border-b border-line px-5 py-3">Telefone</th>
            <th class="border-b border-line px-5 py-3">Conversas</th>
            <th class="border-b border-line px-5 py-3">Última interação</th>
            <th class="border-b border-line px-5 py-3 text-right">Ações</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="5" class="px-5 py-10 text-center text-ink-muted">
              <LoaderCircle class="mx-auto h-5 w-5 animate-spin" />
            </td>
          </tr>
          <tr v-else-if="!contacts.length">
            <td colspan="5" class="px-5 py-10 text-center text-sm text-ink-muted">
              Nenhum contato encontrado
            </td>
          </tr>
          <tr
            v-for="contact in contacts"
            v-else
            :key="contact.id"
            class="border-b border-line hover:bg-canvas"
          >
            <td class="border-b border-line px-5 py-3">
              <div v-if="editingContactId === contact.id" class="flex min-w-0 items-center gap-2">
                <input
                  v-model="editingName"
                  maxlength="160"
                  class="h-9 min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 text-sm text-ink outline-none focus:ring-1 focus:ring-fluvius-500/30"
                  @keyup.enter="saveEditing(contact)"
                  @keyup.escape="stopEditing"
                />
                <button
                  type="button"
                  class="grid h-9 w-9 place-items-center rounded-lg bg-fluvius-700 text-white transition hover:bg-fluvius-800"
                  title="Salvar nome"
                  @click="saveEditing(contact)"
                >
                  <Save class="h-4 w-4" />
                </button>
              </div>
              <div v-else class="flex min-w-0 items-center gap-3">
                <div class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-success-soft text-sm font-semibold text-success-strong">
                  {{ contact.display_name.slice(0, 1).toUpperCase() }}
                </div>
                <div class="min-w-0">
                  <p class="truncate font-medium text-ink">{{ contact.display_name }}</p>
                  <p class="truncate text-xs text-ink-muted">Direto</p>
                </div>
              </div>
            </td>
            <td class="border-b border-line px-5 py-3 font-medium text-ink">
              {{ phoneLabel(contact.phone_number) }}
            </td>
            <td class="border-b border-line px-5 py-3 text-ink-secondary">
              {{ contact.conversation_count }}
            </td>
            <td class="border-b border-line px-5 py-3 text-ink-secondary">
              {{ dateLabel(contact.last_interaction_at) }}
            </td>
            <td class="border-b border-line px-5 py-3">
              <div class="flex justify-end gap-2">
                <button
                  type="button"
                  class="grid h-9 w-9 place-items-center rounded-lg border border-line text-ink-secondary transition hover:bg-panel hover:text-ink"
                  title="Editar nome"
                  @click="editingContactId === contact.id ? stopEditing() : startEditing(contact)"
                >
                  <X v-if="editingContactId === contact.id" class="h-4 w-4" />
                  <Pencil v-else class="h-4 w-4" />
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-neutral-action px-3 text-xs font-medium text-white transition hover:bg-neutral-action disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="!selectedChannelId || startingContactId === contact.id"
                  @click="openConversation(contact)"
                >
                  <LoaderCircle v-if="startingContactId === contact.id" class="h-4 w-4 animate-spin" />
                  <MessageCircle v-else class="h-4 w-4" />
                  Abrir
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="flex shrink-0 items-center justify-between border-t border-line bg-panel px-5 py-3 text-sm text-ink-secondary">
      <span>{{ total }} contato{{ total === 1 ? '' : 's' }}</span>
      <div class="flex gap-2">
        <button
          type="button"
          class="rounded-lg border border-line px-3 py-1.5 font-medium text-ink disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasPreviousPage || loading"
          @click="changePage(-1)"
        >
          Anterior
        </button>
        <button
          type="button"
          class="rounded-lg border border-line px-3 py-1.5 font-medium text-ink disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasNextPage || loading"
          @click="changePage(1)"
        >
          Próxima
        </button>
      </div>
    </footer>
  </div>
</template>
