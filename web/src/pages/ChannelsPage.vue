<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
} from 'vue'
import {
  Check,
  CheckCircle2,
  Clipboard,
  LoaderCircle,
  Plus,
  QrCode,
  RefreshCw,
  Smartphone,
  Wifi,
  X,
} from 'lucide-vue-next'
import {
  connectChannel,
  createChannel,
  getChannelStatus,
  listChannels,
} from '../api/channels'
import type { ChannelConnectionResult } from '../api/channels'
import type { Channel, ChannelStatus } from '../api/types'
import ChannelStatusBadge from '../components/ChannelStatusBadge.vue'

const QR_REFRESH_INTERVAL = 30_000
const STATUS_POLL_INTERVAL = 3_000

const channels = ref<Channel[]>([])
const error = ref('')
const notice = ref('')
const loadingChannels = ref(true)
const creating = ref(false)
const showCreateForm = ref(false)
const form = reactive({
  name: '',
  phone_number: '',
  provisioning_key: crypto.randomUUID(),
})
const connection = reactive<{
  channel: Channel | null
  status: ChannelStatus
  qrCode: string | null
  pairingCode: string | null
  error: string
  loading: boolean
  copied: boolean
}>({
  channel: null,
  status: 'disconnected',
  qrCode: null,
  pairingCode: null,
  error: '',
  loading: false,
  copied: false,
})

let statusTimer: number | null = null
let qrRefreshTimer: number | null = null
let closeTimer: number | null = null
let requestGeneration = 0
let statusRequestRunning = false

const qrImageSource = computed(() => safeQrImageSource(connection.qrCode))
const canShowPairingCode = computed(
  () => Boolean(connection.pairingCode && !qrImageSource.value),
)

function safeQrImageSource(value: string | null) {
  if (!value) return null
  const compact = value.trim().replace(/\s/g, '')
  const prefixed = compact.match(
    /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/,
  )
  if (prefixed) return compact
  if (compact.length >= 128 && /^[A-Za-z0-9+/]+={0,2}$/.test(compact)) {
    return `data:image/png;base64,${compact}`
  }
  return null
}

function updateChannelStatus(channelId: string, status: ChannelStatus) {
  const channel = channels.value.find((item) => item.id === channelId)
  if (channel) channel.status = status
  if (connection.channel?.id === channelId) {
    connection.channel.status = status
    connection.status = status
  }
}

function clearConnectionTimers() {
  if (statusTimer !== null) window.clearInterval(statusTimer)
  if (qrRefreshTimer !== null) window.clearTimeout(qrRefreshTimer)
  if (closeTimer !== null) window.clearTimeout(closeTimer)
  statusTimer = null
  qrRefreshTimer = null
  closeTimer = null
}

function completeConnection() {
  clearConnectionTimers()
  connection.error = ''
  connection.qrCode = null
  connection.pairingCode = null
  if (connection.channel) {
    updateChannelStatus(connection.channel.id, 'connected')
  }
  closeTimer = window.setTimeout(closeConnection, 1_500)
}

function applyConnectionResult(result: ChannelConnectionResult) {
  if (!connection.channel) return
  updateChannelStatus(connection.channel.id, result.status)
  connection.qrCode = result.qr_code
  connection.pairingCode = result.pairing_code
  connection.error = result.error || ''
  if (result.status === 'connected') completeConnection()
}

function scheduleQrRefresh() {
  if (qrRefreshTimer !== null) window.clearTimeout(qrRefreshTimer)
  qrRefreshTimer = window.setTimeout(() => {
    void requestConnection(false)
  }, QR_REFRESH_INTERVAL)
}

function startStatusPolling() {
  if (statusTimer !== null || connection.status === 'connected') return
  statusTimer = window.setInterval(() => {
    void pollStatus()
  }, STATUS_POLL_INTERVAL)
}

async function requestConnection(showLoading = true) {
  const channel = connection.channel
  if (!channel) return
  const generation = ++requestGeneration
  if (showLoading) connection.loading = true
  connection.error = ''
  connection.copied = false
  try {
    const result = await connectChannel(channel.id)
    if (generation !== requestGeneration || connection.channel?.id !== channel.id) return
    applyConnectionResult(result)
    if (result.status !== 'connected' && result.status !== 'failed') {
      startStatusPolling()
      scheduleQrRefresh()
    }
  } catch (exception) {
    if (generation !== requestGeneration || connection.channel?.id !== channel.id) return
    connection.error =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível iniciar a conexão'
  } finally {
    if (generation === requestGeneration) connection.loading = false
  }
}

async function pollStatus() {
  const channel = connection.channel
  if (!channel || statusRequestRunning || document.visibilityState !== 'visible') return
  statusRequestRunning = true
  try {
    const result = await getChannelStatus(channel.id)
    if (connection.channel?.id !== channel.id) return
    updateChannelStatus(channel.id, result.status)
    if (result.status === 'connected') {
      completeConnection()
    } else if (result.error) {
      connection.error = result.error
    }
  } catch (exception) {
    if (connection.channel?.id === channel.id) {
      connection.error =
        exception instanceof Error
          ? exception.message
          : 'Não foi possível consultar o status'
    }
  } finally {
    statusRequestRunning = false
  }
}

async function refresh() {
  loadingChannels.value = true
  error.value = ''
  try {
    channels.value = await listChannels()
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar os canais'
  } finally {
    loadingChannels.value = false
  }
}

async function submit() {
  error.value = ''
  notice.value = ''
  creating.value = true
  try {
    const channel = await createChannel({
      name: form.name,
      phone_number: form.phone_number || undefined,
      provider: 'evolution_go',
      provisioning_key: form.provisioning_key,
    })
    const existingChannel = channels.value.find((item) => item.id === channel.id)
    const targetChannel = existingChannel || channel
    if (existingChannel) {
      Object.assign(existingChannel, channel)
      notice.value = `O canal “${existingChannel.name}” foi recuperado com segurança.`
    } else {
      channels.value.push(channel)
    }
    Object.assign(form, {
      name: '',
      phone_number: '',
      provisioning_key: crypto.randomUUID(),
    })
    showCreateForm.value = false
    await openConnection(targetChannel)
  } catch (exception) {
    const message =
      exception instanceof Error ? exception.message : 'Falha ao criar canal'
    await refresh()
    error.value = message
  } finally {
    creating.value = false
  }
}

async function openConnection(channel: Channel) {
  clearConnectionTimers()
  requestGeneration += 1
  Object.assign(connection, {
    channel,
    status: channel.status,
    qrCode: null,
    pairingCode: null,
    error: '',
    loading: false,
    copied: false,
  })
  await requestConnection()
}

function closeConnection() {
  clearConnectionTimers()
  requestGeneration += 1
  connection.channel = null
  connection.loading = false
}

async function copyPairingCode() {
  if (!connection.pairingCode) return
  try {
    await navigator.clipboard.writeText(connection.pairingCode)
    connection.copied = true
    window.setTimeout(() => {
      connection.copied = false
    }, 2_000)
  } catch {
    connection.error = 'Não foi possível copiar o código automaticamente'
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible' && connection.channel) {
    void pollStatus()
  }
}

onMounted(() => {
  void refresh()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  clearConnectionTimers()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <div class="mx-auto max-w-5xl p-6 sm:p-8">
    <div class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-ink">Canais do WhatsApp</h1>
        <p class="mt-1 text-sm text-ink-muted">
          Conecte o WhatsApp sem expor as credenciais da Evolution no navegador.
        </p>
      </div>
      <div class="inline-flex items-center gap-2 text-xs font-medium text-ink-muted">
        <Wifi class="h-4 w-4 text-fluvius-700" />
        Gateway protegido pela API
      </div>
    </div>

    <div
      v-if="!loadingChannels && channels.length && !showCreateForm"
      class="mt-6 flex flex-col gap-4 rounded-lg border border-info/30 bg-info-soft p-5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <p class="font-semibold text-info-strong">Seu canal já está cadastrado</p>
        <p class="mt-1 max-w-2xl text-sm leading-5 text-info-strong">
          Use Conectar ou Verificar no canal abaixo. Você pode adicionar outros números
          sem abrir o Evolution Manager ou configurar tokens manualmente.
        </p>
      </div>
      <button
        class="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-info/30 bg-panel px-3 py-2 text-sm font-semibold text-info-strong transition hover:bg-info-soft"
        @click="showCreateForm = true; notice = ''"
      >
        <Plus class="h-4 w-4" />
        Adicionar outro canal
      </button>
    </div>

    <form
      v-if="!loadingChannels && (!channels.length || showCreateForm)"
      class="mt-6 grid gap-4 rounded-lg border border-line bg-panel p-5 shadow-sm sm:grid-cols-2"
      @submit.prevent="submit"
    >
      <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
        Nome do canal
        <input
          v-model="form.name"
          required
          maxlength="120"
          placeholder="Atendimento principal"
          class="rounded-lg border border-line-strong px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
        />
      </label>
      <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
        Número
        <input
          v-model="form.phone_number"
          maxlength="32"
          placeholder="Opcional"
          class="rounded-lg border border-line-strong px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
        />
      </label>
      <div class="sm:col-span-2 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p class="max-w-2xl text-xs leading-5 text-ink-muted">
          O Fluvius criará uma instância isolada, protegerá a credencial e abrirá o
          QR Code. Nenhum acesso ao Manager é necessário.
        </p>
        <div class="flex items-center justify-end gap-2">
          <button
            v-if="channels.length"
            type="button"
            class="rounded-lg px-3 py-2.5 text-sm font-semibold text-ink-muted transition hover:bg-panel-muted hover:text-ink-secondary"
            @click="showCreateForm = false"
          >
            Cancelar
          </button>
          <button
            :disabled="creating"
            class="inline-flex items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-fluvius-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <LoaderCircle v-if="creating" class="h-4 w-4 animate-spin" />
            <Smartphone v-else class="h-4 w-4" />
            {{ creating ? 'Criando instância…' : 'Criar e conectar' }}
          </button>
        </div>
      </div>
    </form>

    <p
      v-if="notice"
      role="status"
      class="mt-4 rounded-lg border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-strong"
    >
      {{ notice }}
    </p>

    <p
      v-if="error"
      role="alert"
      class="mt-4 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger-strong"
    >
      {{ error }}
    </p>

    <div class="mt-5 overflow-hidden rounded-lg border border-line bg-panel shadow-sm">
      <div v-if="loadingChannels" class="grid place-items-center p-12 text-ink-muted">
        <LoaderCircle class="h-6 w-6 animate-spin" />
        <span class="mt-2 text-sm">Carregando canais…</span>
      </div>
      <div
        v-for="channel in channels"
        v-else
        :key="channel.id"
        class="flex flex-col gap-4 border-b border-line p-5 last:border-b-0 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex min-w-0 items-center gap-3">
          <div class="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-fluvius-50 text-fluvius-700">
            <Smartphone class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <div class="truncate font-semibold text-ink">{{ channel.name }}</div>
            <div class="mt-0.5 truncate text-sm text-ink-muted">
              {{ channel.phone_number || 'Número identificado após a conexão' }}
            </div>
          </div>
        </div>
        <div class="flex items-center justify-between gap-3 sm:justify-end">
          <ChannelStatusBadge :status="channel.status" />
          <button
            v-if="channel.status !== 'connected'"
            class="inline-flex items-center gap-2 rounded-lg border border-line-strong px-3 py-2 text-sm font-semibold text-ink-secondary transition hover:border-fluvius-300 hover:bg-fluvius-50 hover:text-fluvius-800"
            @click="openConnection(channel)"
          >
            <QrCode class="h-4 w-4" />
            Conectar
          </button>
          <button
            v-else
            class="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-ink-muted transition hover:bg-canvas"
            @click="openConnection(channel)"
          >
            <RefreshCw class="h-4 w-4" />
            Verificar
          </button>
        </div>
      </div>
      <p v-if="!loadingChannels && !channels.length" class="p-10 text-center text-sm text-ink-muted">
        Nenhum canal cadastrado.
      </p>
    </div>
  </div>

  <Teleport to="body">
    <div
      v-if="connection.channel"
      class="fixed inset-0 z-50 grid place-items-center bg-black/55 p-4 backdrop-blur-sm"
      @click.self="closeConnection"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="connection-title"
        class="w-full max-w-md overflow-hidden rounded-lg bg-panel shadow-2xl"
      >
        <header class="flex items-start justify-between border-b border-line px-6 py-5">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-fluvius-700">
              Evolution Go
            </p>
            <h2 id="connection-title" class="mt-1 text-lg font-semibold text-ink">
              Conectar {{ connection.channel.name }}
            </h2>
          </div>
          <button
            aria-label="Fechar"
            class="rounded-lg p-2 text-ink-faint transition hover:bg-panel-muted hover:text-ink-secondary"
            @click="closeConnection"
          >
            <X class="h-5 w-5" />
          </button>
        </header>

        <div class="px-6 py-6">
          <div
            v-if="connection.status === 'connected'"
            class="grid place-items-center py-8 text-center"
          >
            <div class="grid h-16 w-16 place-items-center rounded-full bg-success-soft text-success">
              <CheckCircle2 class="h-8 w-8" />
            </div>
            <h3 class="mt-4 text-lg font-semibold text-ink">WhatsApp conectado</h3>
            <p class="mt-1 text-sm text-ink-muted">O canal já está pronto para atender.</p>
          </div>

          <div v-else>
            <div class="flex justify-center">
              <div class="grid h-64 w-64 place-items-center overflow-hidden rounded-lg border border-line bg-canvas p-3">
                <LoaderCircle v-if="connection.loading" class="h-8 w-8 animate-spin text-fluvius-700" />
                <img
                  v-else-if="qrImageSource"
                  :src="qrImageSource"
                  alt="QR Code para conectar o WhatsApp"
                  class="h-full w-full object-contain"
                />
                <div v-else-if="canShowPairingCode" class="px-4 text-center">
                  <p class="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Código de pareamento
                  </p>
                  <button
                    class="mt-3 inline-flex items-center gap-2 rounded-lg bg-panel px-4 py-3 font-mono text-xl font-bold tracking-widest text-ink shadow-sm ring-1 ring-line"
                    @click="copyPairingCode"
                  >
                    {{ connection.pairingCode }}
                    <Check v-if="connection.copied" class="h-4 w-4 text-success" />
                    <Clipboard v-else class="h-4 w-4 text-ink-faint" />
                  </button>
                </div>
                <QrCode v-else class="h-12 w-12 text-ink-faint" />
              </div>
            </div>

            <div class="mt-5 text-center">
              <h3 class="font-semibold text-ink">Leia com o WhatsApp do celular</h3>
              <p class="mt-1 text-sm leading-5 text-ink-muted">
                Abra Aparelhos conectados, toque em Conectar um aparelho e aponte a câmera para o código.
              </p>
            </div>

            <p
              v-if="connection.error"
              role="alert"
              class="mt-4 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger-strong"
            >
              {{ connection.error }}
            </p>

            <div class="mt-5 flex items-center justify-between border-t border-line pt-4">
              <ChannelStatusBadge :status="connection.status" />
              <button
                :disabled="connection.loading"
                class="inline-flex items-center gap-2 rounded-lg border border-line-strong px-3 py-2 text-sm font-semibold text-ink-secondary transition hover:bg-canvas disabled:opacity-50"
                @click="requestConnection()"
              >
                <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': connection.loading }" />
                Gerar novo código
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>
