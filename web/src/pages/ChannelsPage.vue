<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { createChannel, getChannelStatus, listChannels } from '../api/channels'
import type { Channel } from '../api/types'
import ChannelStatusBadge from '../components/ChannelStatusBadge.vue'

const channels = ref<Channel[]>([])
const error = ref('')
const form = reactive({ name: '', phone_number: '', instance_name: '' })

async function refresh() {
  channels.value = await listChannels()
}
async function submit() {
  error.value = ''
  try {
    await createChannel({
      name: form.name,
      phone_number: form.phone_number || undefined,
      provider: 'evolution_go',
      provider_config: { instance_name: form.instance_name },
    })
    Object.assign(form, { name: '', phone_number: '', instance_name: '' })
    await refresh()
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : 'Falha ao criar canal'
  }
}
async function reconnect(channel: Channel) {
  error.value = ''
  try {
    const result = await getChannelStatus(channel.id)
    channel.status = result.status
    if (result.error) {
      error.value = result.error
    }
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : 'Falha ao consultar canal'
  }
}
onMounted(refresh)
</script>

<template>
  <div class="mx-auto max-w-4xl p-8">
    <h1 class="text-2xl font-semibold">Canais do WhatsApp</h1>
    <p class="mt-1 text-sm text-slate-500">A configuração do gateway fica protegida pela API do Fluvius.</p>
    <p class="mt-1 text-xs text-slate-400">Use o nome da instância como referência. O token da instância é configurado somente no arquivo .env da API.</p>
    <form class="mt-6 grid grid-cols-3 gap-3 rounded-xl border border-slate-200 bg-white p-5" @submit.prevent="submit">
      <input v-model="form.name" required placeholder="Nome do canal" class="rounded-lg border border-slate-300 px-3 py-2" />
      <input v-model="form.phone_number" placeholder="Número (opcional)" class="rounded-lg border border-slate-300 px-3 py-2" />
      <input v-model="form.instance_name" required placeholder="Instância no provider" class="rounded-lg border border-slate-300 px-3 py-2" />
      <button class="col-span-3 justify-self-end rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white">Criar canal</button>
    </form>
    <p v-if="error" class="mt-4 text-sm text-rose-600">{{ error }}</p>
    <div class="mt-5 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
      <div v-for="channel in channels" :key="channel.id" class="flex items-center justify-between p-4">
        <div>
          <div class="font-medium">{{ channel.name }}</div>
          <div class="mt-1 text-sm text-slate-500">{{ channel.phone_number || 'Número não informado' }}</div>
        </div>
        <div class="flex items-center gap-3">
          <ChannelStatusBadge :status="channel.status" />
          <button v-if="channel.status !== 'connected'" class="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50" @click="reconnect(channel)">
            Reconectar WhatsApp
          </button>
        </div>
      </div>
      <p v-if="!channels.length" class="p-5 text-sm text-slate-500">Nenhum canal cadastrado.</p>
    </div>
  </div>
</template>
