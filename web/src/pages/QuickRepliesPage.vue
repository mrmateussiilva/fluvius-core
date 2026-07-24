<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { createQuickReply, listQuickReplies } from '../api/quickReplies'
import type { QuickReply } from '../api/types'

const replies = ref<QuickReply[]>([])
const form = reactive({ shortcut: '', title: '', content: '' })

async function refresh() {
  replies.value = await listQuickReplies()
}
async function submit() {
  await createQuickReply(form)
  Object.assign(form, { shortcut: '', title: '', content: '' })
  await refresh()
}
onMounted(refresh)
</script>

<template>
  <div class="mx-auto max-w-4xl p-8">
    <h1 class="text-2xl font-semibold">Respostas rápidas</h1>
    <p class="mt-1 text-sm text-slate-500">Cadastre textos recorrentes usados durante o atendimento.</p>
    <form class="mt-6 grid gap-3 rounded-xl border border-slate-200 bg-white p-5" @submit.prevent="submit">
      <div class="grid grid-cols-2 gap-3">
        <input v-model="form.shortcut" required placeholder="Atalho, ex: horario" class="rounded-lg border border-slate-300 px-3 py-2" />
        <input v-model="form.title" required placeholder="Título" class="rounded-lg border border-slate-300 px-3 py-2" />
      </div>
      <textarea v-model="form.content" required placeholder="Conteúdo da resposta" class="rounded-lg border border-slate-300 px-3 py-2" />
      <button class="justify-self-end rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white">Adicionar</button>
    </form>
    <div class="mt-5 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
      <div v-for="reply in replies" :key="reply.id" class="p-4">
        <div class="font-medium">{{ reply.title }} <span class="text-sm text-slate-400">/{{ reply.shortcut }}</span></div>
        <p class="mt-1 text-sm text-slate-600">{{ reply.content }}</p>
      </div>
    </div>
  </div>
</template>
