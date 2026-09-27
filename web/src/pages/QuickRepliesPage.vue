<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  CheckCircle2,
  LoaderCircle,
  MessageSquareText,
  Plus,
  Search,
  Zap,
} from 'lucide-vue-next'
import { createQuickReply, listQuickReplies } from '../api/quickReplies'
import type { QuickReply } from '../api/types'

const replies = ref<QuickReply[]>([])
const form = reactive({ shortcut: '', title: '', content: '' })
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const search = ref('')

const visibleReplies = computed(() => {
  const query = search.value.trim().toLocaleLowerCase('pt-BR')
  if (!query) return replies.value
  return replies.value.filter((reply) =>
    [reply.shortcut, reply.title, reply.content].some((value) =>
      value.toLocaleLowerCase('pt-BR').includes(query),
    ),
  )
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    replies.value = await listQuickReplies()
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar respostas rápidas'
  } finally {
    loading.value = false
  }
}
async function submit() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const reply = await createQuickReply(form)
    Object.assign(form, { shortcut: '', title: '', content: '' })
    notice.value = `Resposta "${reply.title}" criada.`
    await refresh()
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível criar a resposta rápida'
  } finally {
    saving.value = false
  }
}
onMounted(refresh)
</script>

<template>
  <div class="h-full overflow-y-auto bg-canvas">
    <div class="mx-auto max-w-6xl p-5 sm:p-8">
      <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div class="flex items-center gap-2 text-fluvius-700">
            <Zap class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Atendimento
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight text-ink">
            Respostas rápidas
          </h1>
          <p class="mt-1 max-w-2xl text-sm leading-6 text-ink-muted">
            Organize textos recorrentes para responder clientes com agilidade sem perder o tom humano do atendimento.
          </p>
        </div>
        <div class="rounded-xl border border-line bg-panel px-4 py-3 shadow-sm">
          <p class="text-xs font-medium text-ink-muted">Modelos cadastrados</p>
          <p class="mt-1 text-2xl font-semibold tabular-nums text-ink">
            {{ replies.length }}
          </p>
        </div>
      </header>

      <div
        v-if="notice"
        class="mt-5 flex items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-strong"
      >
        <CheckCircle2 class="h-4 w-4 shrink-0" />
        {{ notice }}
      </div>
      <div
        v-if="error"
        class="mt-5 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger-strong"
      >
        {{ error }}
      </div>

      <div class="mt-6 grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <form class="rounded-xl border border-line bg-panel p-5 shadow-sm sm:p-6" @submit.prevent="submit">
          <div class="flex items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-fluvius-50 text-fluvius-700">
              <Plus class="h-5 w-5" />
            </span>
            <div>
              <h2 class="font-semibold text-ink">Novo modelo</h2>
              <p class="mt-0.5 text-xs leading-5 text-ink-muted">
                Use atalhos curtos para inserir respostas durante a conversa.
              </p>
            </div>
          </div>

          <div class="mt-5 grid gap-3 sm:grid-cols-2">
            <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
              Atalho
              <input
                v-model.trim="form.shortcut"
                required
                maxlength="60"
                placeholder="horario"
                class="h-10 rounded-lg border border-line-strong bg-canvas px-3 text-sm font-normal text-ink outline-none placeholder:text-ink-faint focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
              />
            </label>
            <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
              Título
              <input
                v-model.trim="form.title"
                required
                maxlength="120"
                placeholder="Horário de atendimento"
                class="h-10 rounded-lg border border-line-strong bg-canvas px-3 text-sm font-normal text-ink outline-none placeholder:text-ink-faint focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
              />
            </label>
            <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary sm:col-span-2">
              Conteúdo
              <textarea
                v-model="form.content"
                required
                rows="6"
                placeholder="Olá! Nosso horário de atendimento é..."
                class="rounded-lg border border-line-strong bg-canvas px-3 py-2.5 text-sm font-normal leading-6 text-ink outline-none placeholder:text-ink-faint focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
              />
            </label>
          </div>

          <div class="mt-5 flex justify-end">
            <button
              class="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 text-sm font-semibold text-white transition hover:bg-fluvius-800 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="saving"
            >
              <LoaderCircle v-if="saving" class="h-4 w-4 animate-spin" />
              <Plus v-else class="h-4 w-4" />
              {{ saving ? 'Adicionando...' : 'Adicionar resposta' }}
            </button>
          </div>
        </form>

        <section class="overflow-hidden rounded-xl border border-line bg-panel shadow-sm">
          <div class="border-b border-line p-4 sm:p-5">
            <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 class="font-semibold text-ink">Biblioteca de respostas</h2>
                <p class="mt-0.5 text-xs text-ink-muted">
                  Consulte atalhos já prontos para a operação.
                </p>
              </div>
              <label class="flex h-10 min-w-0 items-center gap-2 rounded-lg border border-line bg-canvas px-3 text-ink-muted sm:w-64">
                <Search class="h-4 w-4 shrink-0" />
                <input
                  v-model="search"
                  type="search"
                  placeholder="Buscar resposta"
                  class="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-muted"
                />
              </label>
            </div>
          </div>

          <div v-if="loading" class="grid min-h-48 place-items-center text-sm text-ink-muted">
            <div class="flex items-center gap-2">
              <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
              Carregando respostas...
            </div>
          </div>
          <div v-else-if="!visibleReplies.length" class="grid min-h-56 place-items-center px-6 text-center">
            <div>
              <div class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-fluvius-50 text-fluvius-700">
                <MessageSquareText class="h-5 w-5" />
              </div>
              <p class="mt-3 text-sm font-medium text-ink">
                {{ search ? 'Nenhuma resposta encontrada' : 'Nenhuma resposta cadastrada' }}
              </p>
              <p class="mx-auto mt-1 max-w-xs text-xs leading-5 text-ink-muted">
                {{ search ? 'Tente outro termo ou limpe a busca.' : 'Crie o primeiro modelo para acelerar mensagens recorrentes.' }}
              </p>
            </div>
          </div>
          <div v-else class="divide-y divide-line">
            <article v-for="reply in visibleReplies" :key="reply.id" class="p-4 transition hover:bg-canvas/70 sm:p-5">
              <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div class="min-w-0">
                  <p class="truncate font-semibold text-ink">{{ reply.title }}</p>
                  <p class="mt-0.5 text-xs font-semibold text-fluvius-700">/{{ reply.shortcut }}</p>
                </div>
                <span class="rounded-full bg-panel-muted px-2.5 py-1 text-[11px] font-medium text-ink-muted">
                  Modelo
                </span>
              </div>
              <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink-secondary">
                {{ reply.content }}
              </p>
            </article>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
