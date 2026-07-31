<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ContactRound,
  DatabaseBackup,
  LoaderCircle,
  MessageSquareMore,
  Play,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  XCircle,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { listChannels } from '../api/channels'
import {
  createSyncRun,
  listSyncRuns,
} from '../api/sync'
import type {
  Channel,
  SyncRun,
  SyncStatus,
  SyncType,
} from '../api/types'
import ChannelStatusBadge from '../components/ChannelStatusBadge.vue'
import { useAuthStore } from '../stores/authStore'

const POLL_INTERVAL = 2_500

const auth = useAuthStore()
const router = useRouter()
const channels = ref<Channel[]>([])
const runs = ref<SyncRun[]>([])
const selectedChannelId = ref('')
const recentDays = ref(7)
const loading = ref(true)
const refreshing = ref(false)
const creatingType = ref<SyncType | null>(null)
const error = ref('')
const notice = ref('')
let pollTimer: number | null = null
let runsRequestActive = false

const selectedChannel = computed(
  () =>
    channels.value.find(
      (channel) => channel.id === selectedChannelId.value,
    ) || null,
)
const activeRun = computed(
  () =>
    runs.value.find(
      (run) => run.status === 'queued' || run.status === 'running',
    ) || null,
)
const contactsAvailable = computed(
  () => selectedChannel.value?.status === 'connected',
)

function syncTypeLabel(type: SyncType) {
  const labels: Record<SyncType, string> = {
    contacts: 'Contatos',
    messages: 'Mensagens recentes',
    all: 'Contatos e mensagens',
  }
  return labels[type]
}

function statusLabel(status: SyncStatus) {
  const labels: Record<SyncStatus, string> = {
    queued: 'Na fila',
    running: 'Em andamento',
    completed: 'Concluída',
    partial: 'Concluída parcialmente',
    failed: 'Falhou',
  }
  return labels[status]
}

function statusClass(status: SyncStatus) {
  if (status === 'completed') return 'bg-emerald-50 text-emerald-700 ring-emerald-100'
  if (status === 'partial') return 'bg-amber-50 text-amber-700 ring-amber-100'
  if (status === 'failed') return 'bg-rose-50 text-rose-700 ring-rose-100'
  return 'bg-sky-50 text-sky-700 ring-sky-100'
}

function progress(run: SyncRun) {
  if (!run.total_items) return run.status === 'completed' ? 100 : 0
  return Math.min(
    100,
    Math.round((run.processed_items / run.total_items) * 100),
  )
}

function itemBreakdown(run: SyncRun) {
  return [
    { label: 'Contatos', value: run.contact_items },
    { label: 'Grupos conhecidos', value: run.group_items },
    { label: 'Eventos', value: run.message_event_items },
    { label: 'Diretório de grupos', value: run.imported_group_items },
  ].filter((item) => item.value > 0)
}

function formatDate(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function refreshRuns(showSpinner = false) {
  if (!selectedChannelId.value || runsRequestActive) return
  const channelId = selectedChannelId.value
  runsRequestActive = true
  if (showSpinner) refreshing.value = true
  try {
    const response = await listSyncRuns(channelId)
    if (selectedChannelId.value === channelId) runs.value = response
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar as sincronizações'
  } finally {
    runsRequestActive = false
    refreshing.value = false
  }
}

async function loadPage() {
  loading.value = true
  error.value = ''
  try {
    channels.value = await listChannels()
    if (
      !selectedChannelId.value ||
      !channels.value.some(
        (channel) => channel.id === selectedChannelId.value,
      )
    ) {
      selectedChannelId.value = channels.value[0]?.id || ''
    }
    await refreshRuns()
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar a administração da empresa'
  } finally {
    loading.value = false
  }
}

async function startSync(type: SyncType) {
  if (!selectedChannel.value || creatingType.value || activeRun.value) return
  if (type !== 'messages' && !contactsAvailable.value) {
    error.value = 'Conecte o canal antes de sincronizar contatos.'
    return
  }
  creatingType.value = type
  error.value = ''
  notice.value = ''
  try {
    const run = await createSyncRun({
      channel_id: selectedChannel.value.id,
      sync_type: type,
      recent_days: recentDays.value,
    })
    runs.value = [run, ...runs.value.filter((item) => item.id !== run.id)]
    notice.value = 'Sincronização enviada para processamento.'
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível iniciar a sincronização'
    await refreshRuns()
  } finally {
    creatingType.value = null
  }
}

watch(selectedChannelId, () => {
  notice.value = ''
  error.value = ''
  void refreshRuns(true)
})

onMounted(async () => {
  await auth.restore()
  if (auth.user?.role !== 'admin') {
    await router.replace('/app/conversations')
    return
  }
  await loadPage()
  pollTimer = window.setInterval(() => {
    if (
      document.visibilityState === 'visible' &&
      (activeRun.value || runs.value.length)
    ) {
      void refreshRuns()
    }
  }, POLL_INTERVAL)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="mx-auto max-w-6xl p-5 sm:p-8">
      <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div class="flex items-center gap-2 text-fluvius-700">
            <ServerCog class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Administração da empresa
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">
            Sincronização operacional
          </h1>
          <p class="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            Atualize perfis conhecidos e reconcilie eventos recentes que ficaram pendentes,
            sem duplicar mensagens ou acessar outro tenant.
          </p>
        </div>
        <div class="flex items-center gap-2">
          <ShieldCheck class="h-4 w-4 text-fluvius-700" />
          <span class="text-xs font-medium text-slate-600">
            Exclusivo para administradores
          </span>
        </div>
      </header>

      <div
        v-if="notice"
        class="mt-5 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
      >
        <CheckCircle2 class="h-4 w-4 shrink-0" />
        {{ notice }}
      </div>
      <div
        v-if="error"
        class="mt-5 flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
      >
        <XCircle class="h-4 w-4 shrink-0" />
        {{ error }}
      </div>

      <div
        v-if="loading"
        class="mt-8 grid min-h-60 place-items-center rounded-2xl border border-slate-200 bg-white"
      >
        <div class="flex items-center gap-2 text-sm text-slate-500">
          <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
          Carregando configurações...
        </div>
      </div>

      <template v-else>
        <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="grid gap-4 md:grid-cols-[1fr_180px_auto] md:items-end">
            <label>
              <span class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Canal do WhatsApp
              </span>
              <select
                v-model="selectedChannelId"
                class="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
              >
                <option v-if="!channels.length" value="">Nenhum canal cadastrado</option>
                <option
                  v-for="channel in channels"
                  :key="channel.id"
                  :value="channel.id"
                >
                  {{ channel.name }} · {{ channel.phone_number || 'sem número' }}
                </option>
              </select>
            </label>
            <label>
              <span class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Período das mensagens
              </span>
              <select
                v-model.number="recentDays"
                class="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
              >
                <option :value="1">Últimas 24 horas</option>
                <option :value="3">Últimos 3 dias</option>
                <option :value="7">Últimos 7 dias</option>
                <option :value="14">Últimos 14 dias</option>
                <option :value="30">Últimos 30 dias</option>
              </select>
            </label>
            <div class="flex h-11 items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 ring-1 ring-slate-200 md:justify-start">
              <span class="text-xs text-slate-500">Status</span>
              <ChannelStatusBadge
                v-if="selectedChannel"
                :status="selectedChannel.status"
              />
              <span v-else class="text-xs text-slate-400">Sem canal</span>
            </div>
          </div>
        </section>

        <section class="mt-5 grid gap-4 lg:grid-cols-3">
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <span class="grid h-11 w-11 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
              <ContactRound class="h-5 w-5" />
            </span>
            <h2 class="mt-4 font-semibold text-slate-900">Atualizar contatos</h2>
            <p class="mt-1 min-h-16 text-sm leading-5 text-slate-500">
              Atualiza nome, foto, recado e disponibilidade de até 50 contatos já
              vinculados ao canal.
            </p>
            <button
              class="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-fluvius-700 px-4 text-sm font-semibold text-white transition hover:bg-fluvius-800 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="
                !selectedChannel ||
                !contactsAvailable ||
                Boolean(activeRun) ||
                Boolean(creatingType)
              "
              @click="startSync('contacts')"
            >
              <LoaderCircle
                v-if="creatingType === 'contacts'"
                class="h-4 w-4 animate-spin"
              />
              <Play v-else class="h-4 w-4" />
              Sincronizar contatos
            </button>
          </article>

          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <span class="grid h-11 w-11 place-items-center rounded-xl bg-sky-50 text-sky-700">
              <MessageSquareMore class="h-5 w-5" />
            </span>
            <h2 class="mt-4 font-semibold text-slate-900">Reconciliar mensagens</h2>
            <p class="mt-1 min-h-16 text-sm leading-5 text-slate-500">
              Reprocessa edições e recibos recentes que já chegaram ao Fluvius e
              aguardavam a mensagem correspondente.
            </p>
            <button
              class="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-sky-700 px-4 text-sm font-semibold text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="
                !selectedChannel || Boolean(activeRun) || Boolean(creatingType)
              "
              @click="startSync('messages')"
            >
              <LoaderCircle
                v-if="creatingType === 'messages'"
                class="h-4 w-4 animate-spin"
              />
              <Play v-else class="h-4 w-4" />
              Reconciliar mensagens
            </button>
          </article>

          <article class="rounded-2xl border border-fluvius-100 bg-fluvius-50/50 p-5 shadow-sm">
            <span class="grid h-11 w-11 place-items-center rounded-xl bg-white text-fluvius-700 ring-1 ring-fluvius-100">
              <DatabaseBackup class="h-5 w-5" />
            </span>
            <h2 class="mt-4 font-semibold text-slate-900">Executar ambas</h2>
            <p class="mt-1 min-h-16 text-sm leading-5 text-slate-500">
              Processa contatos e pendências de mensagens em uma única execução
              rastreável.
            </p>
            <button
              class="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-fluvius-800 px-4 text-sm font-semibold text-white transition hover:bg-fluvius-900 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="
                !selectedChannel ||
                !contactsAvailable ||
                Boolean(activeRun) ||
                Boolean(creatingType)
              "
              @click="startSync('all')"
            >
              <LoaderCircle
                v-if="creatingType === 'all'"
                class="h-4 w-4 animate-spin"
              />
              <Play v-else class="h-4 w-4" />
              Sincronizar tudo
            </button>
          </article>
        </section>

        <aside class="mt-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
          <AlertTriangle class="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p class="text-sm font-semibold">Limite desta primeira versão</p>
            <p class="mt-1 text-xs leading-5 text-amber-800">
              A reconciliação não importa o histórico completo do WhatsApp. O adapter
              atual não oferece esse contrato; apenas eventos recentes já recebidos pelo
              Fluvius são reprocessados.
            </p>
          </div>
        </aside>

        <section class="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <header class="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <div>
              <h2 class="font-semibold text-slate-900">Execuções recentes</h2>
              <p class="mt-0.5 text-xs text-slate-500">
                Progresso persistido por canal e atualizado automaticamente.
              </p>
            </div>
            <button
              class="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
              :disabled="refreshing || !selectedChannelId"
              title="Atualizar execuções"
              @click="refreshRuns(true)"
            >
              <RefreshCw
                class="h-4 w-4"
                :class="refreshing ? 'animate-spin' : ''"
              />
            </button>
          </header>

          <div v-if="runs.length" class="divide-y divide-slate-100">
            <article
              v-for="run in runs"
              :key="run.id"
              class="px-5 py-4"
            >
              <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-medium text-slate-900">
                      {{ syncTypeLabel(run.sync_type) }}
                    </span>
                    <span
                      class="rounded-full px-2 py-1 text-[10px] font-semibold ring-1"
                      :class="statusClass(run.status)"
                    >
                      {{ statusLabel(run.status) }}
                    </span>
                  </div>
                  <div class="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                    <span class="flex items-center gap-1">
                      <Clock3 class="h-3.5 w-3.5" />
                      {{ formatDate(run.started_at || run.created_at) }}
                    </span>
                    <span>{{ run.succeeded_items }} concluídos</span>
                    <span v-if="run.failed_items" class="text-rose-600">
                      {{ run.failed_items }} falhas
                    </span>
                  </div>
                  <div
                    v-if="itemBreakdown(run).length"
                    class="mt-2 flex flex-wrap gap-1.5"
                  >
                    <span
                      v-for="item in itemBreakdown(run)"
                      :key="item.label"
                      class="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-600"
                    >
                      {{ item.label }}: {{ item.value }}
                    </span>
                  </div>
                </div>
                <span class="text-xs font-semibold text-slate-500">
                  {{ run.processed_items }}/{{ run.total_items }}
                </span>
              </div>
              <div class="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  :class="
                    run.status === 'failed'
                      ? 'bg-rose-500'
                      : run.status === 'partial'
                        ? 'bg-amber-500'
                        : 'bg-fluvius-600'
                  "
                  :style="{ width: `${progress(run)}%` }"
                />
              </div>
              <p
                v-if="run.error"
                class="mt-2 text-xs leading-5 text-rose-600"
              >
                {{ run.error }}
              </p>
            </article>
          </div>
          <div v-else class="grid min-h-36 place-items-center px-6 text-center">
            <div>
              <DatabaseBackup class="mx-auto h-6 w-6 text-slate-300" />
              <p class="mt-2 text-sm font-medium text-slate-500">
                Nenhuma sincronização neste canal
              </p>
              <p class="mt-1 text-xs text-slate-400">
                Escolha uma das operações acima para começar.
              </p>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
