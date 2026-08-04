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
      classes: 'border-success/30 bg-success-soft text-success-strong',
    },
    attention: {
      label: 'Operação exige atenção',
      detail: 'Há itens que devem ser revisados pelo administrador.',
      classes: 'border-warning/30 bg-warning-soft text-warning-strong',
    },
    critical: {
      label: 'Operação crítica',
      detail: 'Existe risco de mensagens não serem enviadas normalmente.',
      classes: 'border-danger/30 bg-danger-soft text-danger-strong',
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
    return 'bg-success-soft text-success-strong ring-success/20'
  }
  if (status === 'connecting' || status === 'requires_qr') {
    return 'bg-warning-soft text-warning-strong ring-warning/20'
  }
  return 'bg-danger-soft text-danger-strong ring-danger/20'
}

function reconcileStatusClass(active: boolean) {
  return active
    ? 'bg-success-soft text-success-strong ring-success/20'
    : 'bg-danger-soft text-danger-strong ring-danger/20'
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
  <div class="h-full overflow-y-auto bg-canvas">
    <div class="mx-auto max-w-6xl p-5 sm:p-8">
      <header class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div class="flex items-center gap-2 text-fluvius-700">
            <HeartPulse class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Administração da empresa
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold text-ink">
            Saúde operacional
          </h1>
          <p class="mt-1 max-w-3xl text-sm leading-6 text-ink-muted">
            Monitore filas, workers, entregas e canais da sua empresa sem
            expor informações de outros tenants.
          </p>
        </div>
        <button
          class="flex h-10 items-center justify-center gap-2 rounded-lg border border-line bg-panel px-4 text-sm font-semibold text-ink-secondary shadow-sm transition hover:bg-canvas disabled:opacity-50"
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
        class="mt-6 flex items-center gap-3 rounded-lg border border-danger/30 bg-danger-soft p-4 text-sm text-danger-strong"
      >
        <XCircle class="h-5 w-5 shrink-0" />
        {{ operations.error }}
      </div>

      <div
        v-if="operations.loading && !operations.health"
        class="mt-6 grid min-h-64 place-items-center rounded-lg border border-line bg-panel"
      >
        <div class="flex items-center gap-2 text-sm text-ink-muted">
          <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
          Verificando a operação...
        </div>
      </div>

      <template v-if="operations.health">
        <section
          class="mt-6 flex items-start gap-3 rounded-lg border p-5"
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
          class="mt-5 overflow-hidden rounded-lg border border-line bg-panel shadow-sm"
        >
          <header class="border-b border-line px-5 py-4">
            <h2 class="font-semibold text-ink">Ações necessárias</h2>
          </header>
          <ul class="divide-y divide-line">
            <li
              v-for="issue in operations.health.issues"
              :key="issue"
              class="flex items-start gap-3 px-5 py-3 text-sm text-ink-secondary"
            >
              <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              {{ issue }}
            </li>
          </ul>
        </section>

        <section class="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <ServerCog class="h-5 w-5 text-fluvius-700" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Worker de entregas
            </p>
            <p
              class="mt-1 font-semibold"
              :class="
                operations.health.delivery_worker_online
                  ? 'text-success-strong'
                  : 'text-danger-strong'
              "
            >
              {{ operations.health.delivery_worker_online ? 'Online' : 'Offline' }}
            </p>
          </article>
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <RadioTower class="h-5 w-5 text-info-strong" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Worker de recebimento
            </p>
            <p
              class="mt-1 font-semibold"
              :class="
                operations.health.webhook_worker_online
                  ? 'text-success-strong'
                  : 'text-danger-strong'
              "
            >
              {{ operations.health.webhook_worker_online ? 'Online' : 'Offline' }}
            </p>
            <p class="mt-1 text-xs text-ink-muted">
              {{ operations.health.pending_inbox_events }} na inbox ·
              {{ operations.health.delayed_inbox_events }} atrasada(s)
            </p>
          </article>
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <Wrench class="h-5 w-5 text-info-strong" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Worker de manutenção
            </p>
            <p
              class="mt-1 font-semibold"
              :class="
                operations.health.maintenance_worker_online
                  ? 'text-success-strong'
                  : 'text-warning-strong'
              "
            >
              {{ operations.health.maintenance_worker_online ? 'Online' : 'Offline' }}
            </p>
          </article>
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <Clock3 class="h-5 w-5 text-warning" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Entregas pendentes
            </p>
            <p class="mt-1 text-2xl font-semibold text-ink">
              {{ operations.health.pending_deliveries }}
            </p>
            <p class="mt-1 text-xs text-ink-muted">
              {{ operations.health.delayed_deliveries }} atrasadas
            </p>
          </article>
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <MessageSquareWarning class="h-5 w-5 text-danger" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Falhas em 24 horas
            </p>
            <p class="mt-1 text-2xl font-semibold text-ink">
              {{ operations.health.failed_deliveries_24h }}
            </p>
            <p class="mt-1 text-xs text-ink-muted">
              {{ operations.health.failed_inbox_events_24h }} recebimento(s) com falha ·
              Mais antiga pendente:
              {{ formatDate(operations.health.oldest_pending_at) }}
            </p>
          </article>
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <div class="flex items-start justify-between gap-3">
              <RadioTower class="h-5 w-5 text-info" />
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
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Webhooks pendentes
            </p>
            <p class="mt-1 text-2xl font-semibold text-ink">
              {{ operations.health.pending_provider_events }}
            </p>
            <p class="mt-1 text-xs text-ink-muted">
              {{ operations.health.failed_provider_events }} com erro · mais antigo:
              {{ formatDate(operations.health.oldest_pending_event_at) }}
            </p>
            <p class="mt-2 text-xs text-ink-muted">
              Último lote:
              {{ operations.health.webhook_reconcile.last_resolved_events }}
              resolvido(s) de
              {{ operations.health.webhook_reconcile.last_checked_events }}
              verificado(s)
            </p>
            <p
              v-if="operations.lastReconcile"
              class="mt-1 text-xs text-success-strong"
            >
              Agora:
              {{ operations.lastReconcile.resolved_events }} resolvido(s);
              {{ operations.lastReconcile.remaining_pending_events }} pendente(s)
            </p>
            <button
              class="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-info px-3 text-sm font-semibold text-white transition hover:bg-info-strong disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="
                operations.reconciling ||
                (operations.health.pending_provider_events === 0 &&
                  operations.health.failed_provider_events === 0)
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
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <AlertTriangle class="h-5 w-5 text-warning" />
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Canais sem webhook
            </p>
            <p class="mt-1 text-2xl font-semibold text-ink">
              {{ operations.health.stale_connected_channels }}
            </p>
            <p class="mt-1 text-xs text-ink-muted">
              Conectados há 30+ min sem nenhum evento
            </p>
          </article>
          <article class="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <div class="flex items-start justify-between gap-3">
              <RefreshCw class="h-5 w-5 text-info" />
              <span
                class="rounded-full px-2 py-1 text-[10px] font-semibold ring-1"
                :class="reconcileStatusClass(operations.health.history_reconcile.active)"
              >
                {{
                  operations.health.history_reconcile.active
                    ? 'Auto ativo'
                    : 'Auto parado'
                }}
              </span>
            </div>
            <p class="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
              Histórico do provider
            </p>
            <p class="mt-1 text-2xl font-semibold text-ink">
              {{ operations.health.history_reconcile.last_requested_threads }}
            </p>
            <p class="mt-1 text-xs text-ink-muted">
              thread(s) solicitada(s) no último lote ·
              {{ operations.health.history_reconcile.last_failed_threads }} falha(s)
            </p>
            <p
              v-if="operations.lastHistorySync"
              class="mt-2 text-xs text-success-strong"
            >
              Agora:
              {{ operations.lastHistorySync.requested_threads }} solicitada(s);
              {{ operations.lastHistorySync.failed_threads }} falha(s)
            </p>
            <button
              class="mt-4 flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-info px-3 text-sm font-semibold text-white transition hover:bg-info-strong disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="
                operations.historySyncing ||
                operations.health.connected_channels === 0
              "
              @click="operations.requestHistory()"
            >
              <LoaderCircle
                v-if="operations.historySyncing"
                class="h-4 w-4 animate-spin"
              />
              <RefreshCw v-else class="h-4 w-4" />
              Solicitar histórico
            </button>
          </article>
        </section>

        <section class="mt-5 overflow-hidden rounded-lg border border-line bg-panel shadow-sm">
          <header class="flex items-center justify-between border-b border-line px-5 py-4">
            <div>
              <h2 class="font-semibold text-ink">Canais do WhatsApp</h2>
              <p class="mt-0.5 text-xs text-ink-muted">
                {{ operations.health.connected_channels }} de
                {{ operations.health.total_channels }} conectados
              </p>
            </div>
            <RadioTower class="h-5 w-5 text-fluvius-700" />
          </header>
          <div v-if="operations.health.channels.length" class="divide-y divide-line">
            <article
              v-for="channel in operations.health.channels"
              :key="channel.id"
              class="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div>
                <p class="font-medium text-ink">{{ channel.name }}</p>
                <p class="mt-0.5 text-xs text-ink-muted">
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
                <p class="mt-1.5 text-xs text-ink-faint">
                  Último evento: {{ formatDate(channel.last_event_at) }}
                </p>
                <p
                  v-if="channel.pending_events || channel.failed_events || channel.webhook_stale"
                  class="mt-1 text-xs"
                  :class="
                    channel.failed_events || channel.webhook_stale
                      ? 'text-danger'
                      : 'text-warning'
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
          <div v-else class="px-5 py-10 text-center text-sm text-ink-faint">
            Nenhum canal cadastrado nesta empresa.
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
