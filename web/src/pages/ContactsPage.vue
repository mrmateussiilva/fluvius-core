<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  LoaderCircle,
  MessageCircle,
  Pencil,
  Plus,
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
import type { Channel, ContactListItem } from '../api/types'

const PAGE_SIZE = 30

const router = useRouter()
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
const form = reactive({
  name: '',
  phone_number: '',
})

const connectedChannels = computed(() =>
  channels.value.filter((channel) => channel.status === 'connected'),
)
const hasPreviousPage = computed(() => offset.value > 0)
const hasNextPage = computed(() => offset.value + PAGE_SIZE < total.value)

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
    await Promise.all([loadChannels(), refresh()])
  } catch (exception) {
    error.value =
      exception instanceof Error ? exception.message : 'Não foi possível carregar contatos'
  }
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-[#f7f8f8]">
    <header class="shrink-0 border-b border-[#d8dcdf] bg-white px-5 py-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-fluvius-700">Atendimento</p>
          <h1 class="mt-0.5 text-xl font-semibold tracking-tight text-[#111b21]">Contatos</h1>
        </div>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <form class="flex h-10 min-w-0 items-center gap-2 rounded-lg border border-[#d8dcdf] bg-[#f7f8f8] px-3 text-[#54656f] focus-within:bg-white focus-within:ring-1 focus-within:ring-fluvius-500/30 sm:w-80" @submit.prevent="submitSearch">
            <Search class="h-4 w-4 shrink-0" />
            <input
              v-model="search"
              type="search"
              placeholder="Buscar nome ou telefone"
              class="min-w-0 flex-1 bg-transparent text-[13px] text-[#111b21] outline-none placeholder:text-[#667781]"
            />
            <button
              v-if="search || appliedSearch"
              type="button"
              class="rounded-md p-1 hover:bg-slate-200"
              title="Limpar busca"
              @click="clearSearch"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </form>
          <button
            type="button"
            class="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-900 px-3 text-sm font-medium text-white transition hover:bg-slate-800"
            @click="showCreateForm = !showCreateForm"
          >
            <Plus class="h-4 w-4" />
            Novo
          </button>
        </div>
      </div>
    </header>

    <section class="shrink-0 border-b border-[#d8dcdf] bg-white px-5 py-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <label class="flex min-w-0 items-center gap-2 text-sm text-[#54656f]">
          <MessageCircle class="h-4 w-4 shrink-0 text-fluvius-700" />
          <select
            v-model="selectedChannelId"
            class="h-9 min-w-0 rounded-lg border border-[#d8dcdf] bg-white px-3 text-[13px] font-medium text-[#111b21] outline-none focus:ring-1 focus:ring-fluvius-500/30"
            aria-label="Canal para iniciar conversa"
            :disabled="!connectedChannels.length"
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
          class="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"
        >
          {{ error }}
        </p>
        <p
          v-else-if="notice"
          class="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
        >
          {{ notice }}
        </p>
      </div>
    </section>

    <form
      v-if="showCreateForm"
      class="grid shrink-0 gap-3 border-b border-[#d8dcdf] bg-white px-5 py-4 md:grid-cols-[minmax(0,1fr)_220px_auto]"
      @submit.prevent="submitContact"
    >
      <input
        v-model="form.name"
        required
        maxlength="160"
        placeholder="Nome"
        class="h-10 rounded-lg border border-[#d8dcdf] px-3 text-sm outline-none focus:ring-1 focus:ring-fluvius-500/30"
      />
      <input
        v-model="form.phone_number"
        required
        maxlength="32"
        placeholder="+55 27 99999-9999"
        class="h-10 rounded-lg border border-[#d8dcdf] px-3 text-sm outline-none focus:ring-1 focus:ring-fluvius-500/30"
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
      <table class="min-w-full border-separate border-spacing-0 bg-white text-left text-sm">
        <thead class="sticky top-0 z-10 bg-[#f7f8f8] text-[11px] font-semibold uppercase tracking-[0.12em] text-[#667781]">
          <tr>
            <th class="border-b border-[#d8dcdf] px-5 py-3">Nome</th>
            <th class="border-b border-[#d8dcdf] px-5 py-3">Telefone</th>
            <th class="border-b border-[#d8dcdf] px-5 py-3">Conversas</th>
            <th class="border-b border-[#d8dcdf] px-5 py-3">Última interação</th>
            <th class="border-b border-[#d8dcdf] px-5 py-3 text-right">Ações</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="5" class="px-5 py-10 text-center text-[#667781]">
              <LoaderCircle class="mx-auto h-5 w-5 animate-spin" />
            </td>
          </tr>
          <tr v-else-if="!contacts.length">
            <td colspan="5" class="px-5 py-10 text-center text-sm text-[#667781]">
              Nenhum contato encontrado
            </td>
          </tr>
          <tr
            v-for="contact in contacts"
            v-else
            :key="contact.id"
            class="border-b border-[#edf0f1] hover:bg-[#f7f8f8]"
          >
            <td class="border-b border-[#edf0f1] px-5 py-3">
              <div v-if="editingContactId === contact.id" class="flex min-w-0 items-center gap-2">
                <input
                  v-model="editingName"
                  maxlength="160"
                  class="h-9 min-w-0 flex-1 rounded-lg border border-[#d8dcdf] px-3 text-sm outline-none focus:ring-1 focus:ring-fluvius-500/30"
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
                <div class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-emerald-100 text-sm font-semibold text-emerald-700">
                  {{ contact.display_name.slice(0, 1).toUpperCase() }}
                </div>
                <div class="min-w-0">
                  <p class="truncate font-medium text-[#111b21]">{{ contact.display_name }}</p>
                  <p class="truncate text-xs text-[#667781]">Direto</p>
                </div>
              </div>
            </td>
            <td class="border-b border-[#edf0f1] px-5 py-3 font-medium text-[#111b21]">
              {{ phoneLabel(contact.phone_number) }}
            </td>
            <td class="border-b border-[#edf0f1] px-5 py-3 text-[#54656f]">
              {{ contact.conversation_count }}
            </td>
            <td class="border-b border-[#edf0f1] px-5 py-3 text-[#54656f]">
              {{ dateLabel(contact.last_interaction_at) }}
            </td>
            <td class="border-b border-[#edf0f1] px-5 py-3">
              <div class="flex justify-end gap-2">
                <button
                  type="button"
                  class="grid h-9 w-9 place-items-center rounded-lg border border-[#d8dcdf] text-[#54656f] transition hover:bg-white hover:text-[#111b21]"
                  title="Editar nome"
                  @click="editingContactId === contact.id ? stopEditing() : startEditing(contact)"
                >
                  <X v-if="editingContactId === contact.id" class="h-4 w-4" />
                  <Pencil v-else class="h-4 w-4" />
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-slate-900 px-3 text-xs font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
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

    <footer class="flex shrink-0 items-center justify-between border-t border-[#d8dcdf] bg-white px-5 py-3 text-sm text-[#54656f]">
      <span>{{ total }} contato{{ total === 1 ? '' : 's' }}</span>
      <div class="flex gap-2">
        <button
          type="button"
          class="rounded-lg border border-[#d8dcdf] px-3 py-1.5 font-medium text-[#111b21] disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasPreviousPage || loading"
          @click="changePage(-1)"
        >
          Anterior
        </button>
        <button
          type="button"
          class="rounded-lg border border-[#d8dcdf] px-3 py-1.5 font-medium text-[#111b21] disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!hasNextPage || loading"
          @click="changePage(1)"
        >
          Próxima
        </button>
      </div>
    </footer>
  </div>
</template>
