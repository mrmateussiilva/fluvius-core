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
const form = reactive({ name: '', phone_number: '', instance_name: '' })
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
      provider_config: { instance_name: form.instance_name },
    })
    const existingChannel = channels.value.find((item) => item.id === channel.id)
    const targetChannel = existingChannel || channel
    if (existingChannel) {
      Object.assign(existingChannel, channel)
      notice.value =
        `Essa credencial já pertence ao canal “${existingChannel.name}”. ` +
        'Abrimos o canal existente para você.'
    } else {
      channels.value.push(channel)
    }
    Object.assign(form, { name: '', phone_number: '', instance_name: '' })
    showCreateForm.value = false
    await openConnection(targetChannel)
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : 'Falha ao criar canal'
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
        <h1 class="text-2xl font-semibold text-slate-900">Canais do WhatsApp</h1>
        <p class="mt-1 text-sm text-slate-500">
          Conecte o WhatsApp sem expor as credenciais da Evolution no navegador.
        </p>
      </div>
      <div class="inline-flex items-center gap-2 text-xs font-medium text-slate-500">
        <Wifi class="h-4 w-4 text-fluvius-700" />
        Gateway protegido pela API
      </div>
    </div>

    <div
      v-if="!loadingChannels && channels.length && !showCreateForm"
      class="mt-6 flex flex-col gap-4 rounded-2xl border border-sky-200 bg-sky-50 p-5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <p class="font-semibold text-sky-950">Seu canal já está cadastrado</p>
        <p class="mt-1 max-w-2xl text-sm leading-5 text-sky-800">
          Use Conectar ou Verificar no canal abaixo. Outro nome não cria outra instância:
          um canal adicional precisa de outro token configurado na API.
        </p>
      </div>
      <button
        class="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-sky-300 bg-white px-3 py-2 text-sm font-semibold text-sky-900 transition hover:bg-sky-100"
        @click="showCreateForm = true; notice = ''"
      >
        <Plus class="h-4 w-4" />
        Adicionar outro canal
      </button>
    </div>

    <form
      v-if="!loadingChannels && (!channels.length || showCreateForm)"
      class="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:grid-cols-3"
      @submit.prevent="submit"
    >
      <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
        Nome do canal
        <input
          v-model="form.name"
          required
          maxlength="120"
          placeholder="Atendimento principal"
          class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
        />
      </label>
      <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
        Número
        <input
          v-model="form.phone_number"
          maxlength="32"
          placeholder="Opcional"
          class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
        />
      </label>
      <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
        Referência da instância
        <input
          v-model="form.instance_name"
          required
          placeholder="Ex.: pessoal"
          class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
        />
      </label>
      <div class="sm:col-span-3 flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p class="max-w-2xl text-xs leading-5 text-slate-500">
          A referência identifica uma credencial configurada na API. Mudar apenas esse
          nome não cria uma nova instância Evolution; cada canal adicional precisa de
          outro token.
        </p>
        <div class="flex items-center justify-end gap-2">
          <button
            v-if="channels.length"
            type="button"
            class="rounded-lg px-3 py-2.5 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
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
            {{ creating ? 'Verificando…' : 'Criar e conectar' }}
          </button>
        </div>
      </div>
    </form>

    <p
      v-if="notice"
      role="status"
      class="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
    >
      {{ notice }}
    </p>

    <p
      v-if="error"
      role="alert"
      class="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
    >
      {{ error }}
    </p>

    <div class="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div v-if="loadingChannels" class="grid place-items-center p-12 text-slate-500">
        <LoaderCircle class="h-6 w-6 animate-spin" />
        <span class="mt-2 text-sm">Carregando canais…</span>
      </div>
      <div
        v-for="channel in channels"
        v-else
        :key="channel.id"
        class="flex flex-col gap-4 border-b border-slate-100 p-5 last:border-b-0 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex min-w-0 items-center gap-3">
          <div class="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-fluvius-50 text-fluvius-700">
            <Smartphone class="h-5 w-5" />
          </div>
          <div class="min-w-0">
            <div class="truncate font-semibold text-slate-900">{{ channel.name }}</div>
            <div class="mt-0.5 truncate text-sm text-slate-500">
              {{ channel.phone_number || 'Número identificado após a conexão' }}
            </div>
          </div>
        </div>
        <div class="flex items-center justify-between gap-3 sm:justify-end">
          <ChannelStatusBadge :status="channel.status" />
          <button
            v-if="channel.status !== 'connected'"
            class="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-fluvius-300 hover:bg-fluvius-50 hover:text-fluvius-800"
            @click="openConnection(channel)"
          >
            <QrCode class="h-4 w-4" />
            Conectar
          </button>
          <button
            v-else
            class="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-500 transition hover:bg-slate-50"
            @click="openConnection(channel)"
          >
            <RefreshCw class="h-4 w-4" />
            Verificar
          </button>
        </div>
      </div>
      <p v-if="!loadingChannels && !channels.length" class="p-10 text-center text-sm text-slate-500">
        Nenhum canal cadastrado.
      </p>
    </div>
  </div>

  <Teleport to="body">
    <div
      v-if="connection.channel"
      class="fixed inset-0 z-50 grid place-items-center bg-slate-950/55 p-4 backdrop-blur-sm"
      @click.self="closeConnection"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="connection-title"
        class="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl"
      >
        <header class="flex items-start justify-between border-b border-slate-100 px-6 py-5">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-fluvius-700">
              Evolution Go
            </p>
            <h2 id="connection-title" class="mt-1 text-lg font-semibold text-slate-900">
              Conectar {{ connection.channel.name }}
            </h2>
          </div>
          <button
            aria-label="Fechar"
            class="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
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
            <div class="grid h-16 w-16 place-items-center rounded-full bg-emerald-100 text-emerald-600">
              <CheckCircle2 class="h-8 w-8" />
            </div>
            <h3 class="mt-4 text-lg font-semibold text-slate-900">WhatsApp conectado</h3>
            <p class="mt-1 text-sm text-slate-500">O canal já está pronto para atender.</p>
          </div>

          <div v-else>
            <div class="flex justify-center">
              <div class="grid h-64 w-64 place-items-center overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <LoaderCircle v-if="connection.loading" class="h-8 w-8 animate-spin text-fluvius-700" />
                <img
                  v-else-if="qrImageSource"
                  :src="qrImageSource"
                  alt="QR Code para conectar o WhatsApp"
                  class="h-full w-full object-contain"
                />
                <div v-else-if="canShowPairingCode" class="px-4 text-center">
                  <p class="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    Código de pareamento
                  </p>
                  <button
                    class="mt-3 inline-flex items-center gap-2 rounded-xl bg-white px-4 py-3 font-mono text-xl font-bold tracking-widest text-slate-900 shadow-sm ring-1 ring-slate-200"
                    @click="copyPairingCode"
                  >
                    {{ connection.pairingCode }}
                    <Check v-if="connection.copied" class="h-4 w-4 text-emerald-600" />
                    <Clipboard v-else class="h-4 w-4 text-slate-400" />
                  </button>
                </div>
                <QrCode v-else class="h-12 w-12 text-slate-300" />
              </div>
            </div>

            <div class="mt-5 text-center">
              <h3 class="font-semibold text-slate-900">Leia com o WhatsApp do celular</h3>
              <p class="mt-1 text-sm leading-5 text-slate-500">
                Abra Aparelhos conectados, toque em Conectar um aparelho e aponte a câmera para o código.
              </p>
            </div>

            <p
              v-if="connection.error"
              role="alert"
              class="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-700"
            >
              {{ connection.error }}
            </p>

            <div class="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
              <ChannelStatusBadge :status="connection.status" />
              <button
                :disabled="connection.loading"
                class="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
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
