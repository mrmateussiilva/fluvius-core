<script setup lang="ts">
import { computed, onMounted } from 'vue'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  HeartPulse,
  LoaderCircle,
  MessageSquareWarning,
  RadioTower,
  RefreshCw,
  ServerCog,
  Wrench,
  XCircle,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import type {
  ChannelStatus,
  OperationalStatus,
} from '../api/types'
import { useAuthStore } from '../stores/authStore'
import { useOperationalStore } from '../stores/operationalStore'

const auth = useAuthStore()
const operations = useOperationalStore()
const router = useRouter()

const statusPresentation = computed(() => {
  const presentations: Record<
    OperationalStatus,
    { label: string; detail: string; classes: string }
  > = {
    healthy: {
      label: 'Operação saudável',
      detail: 'Filas, workers e canais estão dentro dos limites esperados.',
      classes: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    },
    attention: {
      label: 'Operação exige atenção',
      detail: 'Há itens que devem ser revisados pelo administrador.',
      classes: 'border-amber-200 bg-amber-50 text-amber-900',
    },
    critical: {
      label: 'Operação crítica',
      detail: 'Existe risco de mensagens não serem enviadas normalmente.',
      classes: 'border-rose-200 bg-rose-50 text-rose-800',
    },
  }
  return presentations[operations.health?.status || 'attention']
})

function formatDate(value: string | null) {
  if (!value) return 'Nenhum evento registrado'
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

function channelStatusLabel(status: ChannelStatus) {
  const labels: Record<ChannelStatus, string> = {
    connected: 'Conectado',
    connecting: 'Conectando',
    requires_qr: 'Aguardando QR',
    disconnected: 'Desconectado',
    failed: 'Falhou',
  }
  return labels[status]
}

function channelStatusClass(status: ChannelStatus) {
  if (status === 'connected') {
    return 'bg-emerald-50 text-emerald-700 ring-emerald-100'
  }
  if (status === 'connecting' || status === 'requires_qr') {
    return 'bg-amber-50 text-amber-700 ring-amber-100'
  }
  return 'bg-rose-50 text-rose-700 ring-rose-100'
}

function reconcileStatusClass(active: boolean) {
  return active
    ? 'bg-emerald-50 text-emerald-700 ring-emerald-100'
    : 'bg-rose-50 text-rose-700 ring-rose-100'
}

onMounted(async () => {
  await auth.restore()
  if (auth.user?.role !== 'admin') {
    await router.replace('/app/conversations')
    return
  }
  await operations.refresh()
})
</script>

<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="mx-auto max-w-6xl p-5 sm:p-8">
      <header class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div class="flex items-center gap-2 text-fluvius-700">
            <HeartPulse class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Administração da empresa
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">
            Saúde operacional
          </h1>
          <p class="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            Monitore filas, workers, entregas e canais da sua empresa sem
            expor informações de outros tenants.
          </p>
        </div>
        <button
          class="flex h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
          :disabled="operations.loading"
          @click="operations.refresh"
        >
          <RefreshCw
            class="h-4 w-4"
            :class="{ 'animate-spin': operations.loading }"
          />
          Atualizar
        </button>
      </header>

      <div
        v-if="operations.error"
        class="mt-6 flex items-center gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"
      >
        <XCircle class="h-5 w-5 shrink-0" />
        {{ operations.error }}
      </div>

      <div
        v-if="operations.loading && !operations.health"
        class="mt-6 grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"
      >
        <div class="flex items-center gap-2 text-sm text-slate-500">
          <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
          Verificando a operação...
        </div>
      </div>

      <template v-if="operations.health">
        <section
          class="mt-6 flex items-start gap-3 rounded-2xl border p-5"
          :class="statusPresentation.classes"
        >
          <CheckCircle2
            v-if="operations.health.status === 'healthy'"
            class="mt-0.5 h-6 w-6 shrink-0"
          />
          <AlertTriangle v-else class="mt-0.5 h-6 w-6 shrink-0" />
          <div>
            <h2 class="font-semibold">{{ statusPresentation.label }}</h2>
            <p class="mt-1 text-sm opacity-80">
              {{ statusPresentation.detail }}
            </p>
            <p class="mt-2 text-xs opacity-70">
              Atualizado em {{ formatDate(operations.health.generated_at) }}
            </p>
          </div>
        </section>

        <section
          v-if="operations.health.issues.length"
          class="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
        >
          <header class="border-b border-slate-100 px-5 py-4">
            <h2 class="font-semibold text-slate-900">Ações necessárias</h2>
          </header>
          <ul class="divide-y divide-slate-100">
            <li
              v-for="issue in operations.health.issues"
              :key="issue"
              class="flex items-start gap-3 px-5 py-3 text-sm text-slate-700"
            >
              <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              {{ issue }}
            </li>
          </ul>
        </section>

        <section class="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <ServerCog class="h-5 w-5 text-fluvius-700" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Worker de entregas
            </p>
            <p
              class="mt-1 font-semibold"
              :class="
                operations.health.delivery_worker_online
                  ? 'text-emerald-700'
                  : 'text-rose-700'
              "
            >
              {{ operations.health.delivery_worker_online ? 'Online' : 'Offline' }}
            </p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <Wrench class="h-5 w-5 text-sky-700" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Worker de manutenção
            </p>
            <p
              class="mt-1 font-semibold"
              :class="
                operations.health.maintenance_worker_online
                  ? 'text-emerald-700'
                  : 'text-amber-700'
              "
            >
              {{ operations.health.maintenance_worker_online ? 'Online' : 'Offline' }}
            </p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <Clock3 class="h-5 w-5 text-amber-600" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Entregas pendentes
            </p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">
              {{ operations.health.pending_deliveries }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ operations.health.delayed_deliveries }} atrasadas
            </p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <MessageSquareWarning class="h-5 w-5 text-rose-600" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Falhas em 24 horas
            </p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">
              {{ operations.health.failed_deliveries_24h }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              Mais antiga pendente:
              {{ formatDate(operations.health.oldest_pending_at) }}
            </p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div class="flex items-start justify-between gap-3">
              <RadioTower class="h-5 w-5 text-violet-700" />
              <span
                class="rounded-full px-2 py-1 text-[10px] font-semibold ring-1"
                :class="reconcileStatusClass(operations.health.webhook_reconcile.active)"
              >
                {{
                  operations.health.webhook_reconcile.active
                    ? 'Auto ativo'
                    : 'Auto parado'
                }}
              </span>
            </div>
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Webhooks pendentes
            </p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">
              {{ operations.health.pending_provider_events }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ operations.health.failed_provider_events }} com erro · mais antigo:
              {{ formatDate(operations.health.oldest_pending_event_at) }}
            </p>
            <p class="mt-2 text-xs text-slate-500">
              Último lote:
              {{ operations.health.webhook_reconcile.last_resolved_events }}
              resolvido(s) de
              {{ operations.health.webhook_reconcile.last_checked_events }}
              verificado(s)
            </p>
            <p
              v-if="operations.lastReconcile"
              class="mt-1 text-xs text-emerald-700"
            >
              Agora:
              {{ operations.lastReconcile.resolved_events }} resolvido(s);
              {{ operations.lastReconcile.remaining_pending_events }} pendente(s)
            </p>
            <button
              class="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-violet-700 px-3 text-sm font-semibold text-white transition hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="
                operations.reconciling ||
                operations.health.pending_provider_events === 0
              "
              @click="operations.reconcile()"
            >
              <LoaderCircle
                v-if="operations.reconciling"
                class="h-4 w-4 animate-spin"
              />
              <RefreshCw v-else class="h-4 w-4" />
              Reconciliar agora
            </button>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <AlertTriangle class="h-5 w-5 text-amber-600" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Canais sem webhook
            </p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">
              {{ operations.health.stale_connected_channels }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              Conectados há 30+ min sem nenhum evento
            </p>
          </article>
        </section>

        <section class="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <header class="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 class="font-semibold text-slate-900">Canais do WhatsApp</h2>
              <p class="mt-0.5 text-xs text-slate-500">
                {{ operations.health.connected_channels }} de
                {{ operations.health.total_channels }} conectados
              </p>
            </div>
            <RadioTower class="h-5 w-5 text-fluvius-700" />
          </header>
          <div v-if="operations.health.channels.length" class="divide-y divide-slate-100">
            <article
              v-for="channel in operations.health.channels"
              :key="channel.id"
              class="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div>
                <p class="font-medium text-slate-900">{{ channel.name }}</p>
                <p class="mt-0.5 text-xs text-slate-500">
                  {{ channel.phone_number || 'Número ainda não informado' }}
                </p>
              </div>
              <div class="sm:text-right">
                <span
                  class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1"
                  :class="channelStatusClass(channel.status)"
                >
                  {{ channelStatusLabel(channel.status) }}
                </span>
                <p class="mt-1.5 text-xs text-slate-400">
                  Último evento: {{ formatDate(channel.last_event_at) }}
                </p>
                <p
                  v-if="channel.pending_events || channel.failed_events || channel.webhook_stale"
                  class="mt-1 text-xs"
                  :class="
                    channel.failed_events || channel.webhook_stale
                      ? 'text-rose-600'
                      : 'text-amber-600'
                  "
                >
                  <span v-if="channel.pending_events">
                    {{ channel.pending_events }} pendente(s)
                  </span>
                  <span v-if="channel.failed_events">
                    · {{ channel.failed_events }} erro(s)
                  </span>
                  <span v-if="channel.webhook_stale"> · sem webhook</span>
                </p>
              </div>
            </article>
          </div>
          <div v-else class="px-5 py-10 text-center text-sm text-slate-400">
            Nenhum canal cadastrado nesta empresa.
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
