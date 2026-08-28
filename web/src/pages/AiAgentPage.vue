<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertCircle,
  Bot,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Play,
  RotateCcw,
  Save,
  Send,
  Sliders,
  Sparkles,
  User,
  Zap,
} from 'lucide-vue-next'
import { fetchAiConfig, saveAiConfig, simulateAi } from '../api/ai'
import { listChannels } from '../api/channels'
import type {
  AiConfigRead,
  Channel,
  SimulationMessage,
} from '../api/types'

const channels = ref<Channel[]>([])
const selectedChannelId = ref<string>('')
const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)
const successMessage = ref<string | null>(null)

// AI Config Form State
const isEnabled = ref(false)
const provider = ref('openai')
const modelName = ref('gpt-4o-mini')
const apiKey = ref('')
const hasApiKey = ref(false)
const showApiKey = ref(false)
const botName = ref('IA Assistente')
const systemPrompt = ref('')
const handoffPrompt = ref('')
const temperature = ref(0.3)
const maxTokens = ref(500)

// Simulator State
const simMessages = ref<SimulationMessage[]>([
  { role: 'assistant', content: 'Olá! Sou a assistente virtual da empresa. Como posso te ajudar hoje?' },
])
const simInput = ref('')
const simLoading = ref(false)
const simHandoffNote = ref<string | null>(null)

const selectedChannel = computed(() =>
  channels.value.find((c) => c.id === selectedChannelId.value),
)

const providerPresets: Record<string, string[]> = {
  openai: ['gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo'],
  gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash'],
  groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
  deepseek: ['deepseek-chat', 'deepseek-coder'],
}

onMounted(async () => {
  try {
    channels.value = await listChannels()
    if (channels.value.length > 0) {
      selectedChannelId.value = channels.value[0].id
    }
  } catch (err: any) {
    error.value = err?.message || 'Falha ao carregar canais do WhatsApp.'
  } finally {
    loading.value = false
  }
})

watch(selectedChannelId, async (newId) => {
  if (!newId) return
  await loadChannelConfig(newId)
})

watch(provider, (newProv) => {
  const presets = providerPresets[newProv]
  if (presets && !presets.includes(modelName.value)) {
    modelName.value = presets[0]
  }
})

async function loadChannelConfig(channelId: string) {
  loading.value = true
  error.value = null
  successMessage.value = null
  try {
    const config: AiConfigRead = await fetchAiConfig(channelId)
    isEnabled.value = config.is_enabled
    provider.value = config.provider
    modelName.value = config.model_name
    hasApiKey.value = config.has_api_key
    apiKey.value = ''
    botName.value = config.bot_name
    systemPrompt.value = config.system_prompt
    handoffPrompt.value = config.handoff_prompt
    temperature.value = config.temperature
    maxTokens.value = config.max_tokens
    resetSimulator()
  } catch (err: any) {
    error.value = err?.message || 'Falha ao carregar configurações de IA.'
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  if (!selectedChannelId.value) return
  saving.value = true
  error.value = null
  successMessage.value = null
  try {
    const updated = await saveAiConfig(selectedChannelId.value, {
      is_enabled: isEnabled.value,
      provider: provider.value,
      model_name: modelName.value,
      api_key: apiKey.value ? apiKey.value : undefined,
      bot_name: botName.value,
      system_prompt: systemPrompt.value,
      handoff_prompt: handoffPrompt.value,
      temperature: temperature.value,
      max_tokens: maxTokens.value,
    })
    hasApiKey.value = updated.has_api_key
    apiKey.value = ''
    successMessage.value = 'Configurações do Agente de IA salvas com sucesso!'
    setTimeout(() => {
      successMessage.value = null
    }, 4000)
  } catch (err: any) {
    error.value = err?.message || 'Erro ao salvar configurações do Agente de IA.'
  } finally {
    saving.value = false
  }
}

function resetSimulator() {
  simMessages.value = [
    {
      role: 'assistant',
      content: `Olá! Sou ${botName.value || 'a assistente virtual'}. Como posso te ajudar hoje?`,
    },
  ]
  simHandoffNote.value = null
}

async function handleSimulateSend() {
  const text = simInput.value.trim()
  if (!text || simLoading.value || !selectedChannelId.value) return

  simMessages.value.push({ role: 'user', content: text })
  simInput.value = ''
  simLoading.value = true
  simHandoffNote.value = null

  try {
    const res = await simulateAi(selectedChannelId.value, {
      messages: simMessages.value,
      system_prompt: systemPrompt.value,
      handoff_prompt: handoffPrompt.value,
    })

    simMessages.value.push({ role: 'assistant', content: res.reply })
    if (res.handoff_triggered) {
      simHandoffNote.value = res.handoff_reason || 'Transbordo acionado pela IA'
    }
  } catch (err: any) {
    simMessages.value.push({
      role: 'assistant',
      content: `[Erro na simulação: ${err?.message || 'Certifique-se de que a Chave de API está salva'}]`,
    })
  } finally {
    simLoading.value = false
  }
}
</script>

<template>
  <div class="soft-scrollbar flex-1 overflow-y-auto bg-canvas p-4 sm:p-6 lg:p-8">
    <div class="mx-auto max-w-7xl space-y-6">
      <!-- Header -->
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div class="flex items-center gap-2.5">
            <div class="grid h-10 w-10 place-items-center rounded-xl bg-purple-600/15 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300">
              <Bot class="h-5 w-5" />
            </div>
            <div>
              <h1 class="text-xl font-bold tracking-tight text-ink sm:text-2xl">
                Agente de IA e Pré-Atendimento
              </h1>
              <p class="text-xs text-ink-secondary sm:text-sm">
                Automatize o primeiro contato no WhatsApp com inteligência artificial e transbordo humano seguro.
              </p>
            </div>
          </div>
        </div>

        <!-- Channel Picker -->
        <div class="flex items-center gap-2">
          <label for="channel-select" class="text-xs font-semibold text-ink-muted">Canal:</label>
          <select
            id="channel-select"
            v-model="selectedChannelId"
            class="h-9 rounded-lg border border-line bg-panel px-3 text-xs font-medium text-ink shadow-sm outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/20"
          >
            <option v-for="ch in channels" :key="ch.id" :value="ch.id">
              {{ ch.name }} ({{ ch.phone_number || 'Sem número' }})
            </option>
          </select>
        </div>
      </div>

      <!-- Alerts -->
      <div
        v-if="error"
        class="flex items-center gap-3 rounded-lg border border-danger/30 bg-danger-soft p-3.5 text-xs text-danger-strong"
      >
        <AlertCircle class="h-4 w-4 shrink-0" />
        <span class="flex-1">{{ error }}</span>
      </div>

      <div
        v-if="successMessage"
        class="flex items-center gap-3 rounded-lg border border-success/30 bg-success-soft p-3.5 text-xs text-success-strong"
      >
        <Check class="h-4 w-4 shrink-0" />
        <span class="flex-1 font-medium">{{ successMessage }}</span>
      </div>

      <div v-if="!channels.length && !loading" class="rounded-xl border border-line bg-panel p-12 text-center text-ink-muted">
        <Bot class="mx-auto h-12 w-12 text-ink-faint opacity-50" />
        <h3 class="mt-4 text-base font-semibold text-ink">Nenhum canal do WhatsApp encontrado</h3>
        <p class="mt-1 text-xs">Crie e conecte um canal de WhatsApp primeiro para habilitar o Agente de IA.</p>
      </div>

      <div v-else class="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <!-- Configuration Column (7 cols) -->
        <div class="space-y-6 lg:col-span-7">
          <!-- Card 1: Activation & Provider -->
          <div class="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div class="flex items-center justify-between border-b border-line pb-4">
              <div>
                <h2 class="text-sm font-semibold text-ink">Ativação no WhatsApp</h2>
                <p class="text-xs text-ink-muted">
                  Quando ativo, a IA responde a novos clientes até que um atendente assuma.
                </p>
              </div>
              <label class="relative inline-flex cursor-pointer items-center">
                <input
                  v-model="isEnabled"
                  type="checkbox"
                  class="peer sr-only"
                />
                <div class="peer h-6 w-11 rounded-full bg-line-strong transition peer-checked:bg-purple-600 peer-focus:ring-2 peer-focus:ring-purple-500/20 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:after:translate-x-full" />
              </label>
            </div>

            <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="block text-xs font-medium text-ink-secondary">Nome do Agente (Bot)</label>
                <input
                  v-model="botName"
                  type="text"
                  placeholder="Ex: Sofia - Atendente Virtual"
                  class="mt-1 h-9 w-full rounded-lg border border-line bg-panel px-3 text-xs text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
                />
              </div>

              <div>
                <label class="block text-xs font-medium text-ink-secondary">Provedor de LLM</label>
                <select
                  v-model="provider"
                  class="mt-1 h-9 w-full rounded-lg border border-line bg-panel px-3 text-xs text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
                >
                  <option value="openai">OpenAI (Oficial)</option>
                  <option value="gemini">Google Gemini (OpenAI Endpoint)</option>
                  <option value="groq">Groq (Ultra Rápido)</option>
                  <option value="deepseek">DeepSeek AI</option>
                </select>
              </div>

              <div>
                <label class="block text-xs font-medium text-ink-secondary">Modelo</label>
                <input
                  v-model="modelName"
                  type="text"
                  placeholder="gpt-4o-mini"
                  class="mt-1 h-9 w-full rounded-lg border border-line bg-panel px-3 text-xs text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
                />
                <div class="mt-1 flex flex-wrap gap-1">
                  <button
                    v-for="preset in providerPresets[provider] || []"
                    :key="preset"
                    type="button"
                    class="rounded bg-panel-muted px-1.5 py-0.5 text-[10px] text-ink-muted hover:bg-line"
                    @click="modelName = preset"
                  >
                    {{ preset }}
                  </button>
                </div>
              </div>

              <div>
                <div class="flex items-center justify-between">
                  <label class="block text-xs font-medium text-ink-secondary">Chave de API (Secret Key)</label>
                  <span v-if="hasApiKey" class="text-[10px] font-semibold text-success">
                    ✓ Chave configurada
                  </span>
                </div>
                <div class="relative mt-1">
                  <input
                    v-model="apiKey"
                    :type="showApiKey ? 'text' : 'password'"
                    :placeholder="hasApiKey ? '•••••••••••••••• (deixe vazio para manter)' : 'sk-...'"
                    class="h-9 w-full rounded-lg border border-line bg-panel pl-3 pr-8 text-xs text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15"
                  />
                  <button
                    type="button"
                    class="absolute right-2 top-2 text-ink-muted hover:text-ink"
                    @click="showApiKey = !showApiKey"
                  >
                    <EyeOff v-if="showApiKey" class="h-4 w-4" />
                    <Eye v-else class="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Card 2: Prompts and Behavior -->
          <div class="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <h2 class="text-sm font-semibold text-ink">Personalidade e Instruções do Negócio</h2>
            <p class="text-xs text-ink-muted">
              Defina o tom de voz, regras de atendimento, catálogo básico e informações que a IA deve saber.
            </p>

            <div class="mt-4 space-y-4">
              <div>
                <label class="block text-xs font-semibold text-ink-secondary">
                  Prompt do Sistema (Instruções Principais)
                </label>
                <textarea
                  v-model="systemPrompt"
                  rows="6"
                  placeholder="Ex: Você é a atendente virtual da loja X. Seja cordial, tire dúvidas sobre horário (8h às 18h) e valores de frete..."
                  class="mt-1 w-full rounded-lg border border-line bg-panel p-3 text-xs leading-relaxed text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15 font-mono"
                />
              </div>

              <div>
                <label class="block text-xs font-semibold text-ink-secondary">
                  Regras de Transbordo (Handoff para Humano)
                </label>
                <textarea
                  v-model="handoffPrompt"
                  rows="3"
                  placeholder="Ex: Transfira para um atendente humano caso o cliente solicite, queira negociar dívida ou demonstre insatisfação."
                  class="mt-1 w-full rounded-lg border border-line bg-panel p-3 text-xs leading-relaxed text-ink outline-none focus:border-fluvius-500 focus:ring-2 focus:ring-fluvius-500/15 font-mono"
                />
              </div>

              <div class="grid grid-cols-2 gap-4 border-t border-line pt-4">
                <div>
                  <label class="block text-xs font-medium text-ink-secondary">
                    Temperatura (Criatividade): {{ temperature }}
                  </label>
                  <input
                    v-model.number="temperature"
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    class="mt-2 w-full accent-purple-600"
                  />
                  <span class="text-[10px] text-ink-muted">0 = Mais preciso, 1 = Mais criativo</span>
                </div>
                <div>
                  <label class="block text-xs font-medium text-ink-secondary">
                    Tamanho Máximo da Resposta (Tokens): {{ maxTokens }}
                  </label>
                  <input
                    v-model.number="maxTokens"
                    type="range"
                    min="100"
                    max="1500"
                    step="50"
                    class="mt-2 w-full accent-purple-600"
                  />
                  <span class="text-[10px] text-ink-muted">Limite de caracteres gerados por mensagem</span>
                </div>
              </div>
            </div>

            <div class="mt-6 flex justify-end">
              <button
                type="button"
                class="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-purple-700 active:scale-95 disabled:opacity-50"
                :disabled="saving"
                @click="handleSave"
              >
                <Save class="h-4 w-4" />
                {{ saving ? 'Salvando...' : 'Salvar Configurações' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Simulator Column (5 cols) -->
        <div class="lg:col-span-5">
          <div class="flex h-[620px] flex-col rounded-xl border border-line bg-panel shadow-sm">
            <!-- Simulator Header -->
            <div class="flex items-center justify-between border-b border-line px-4 py-3 bg-panel-muted/50 rounded-t-xl">
              <div class="flex items-center gap-2">
                <Sparkles class="h-4 w-4 text-purple-600 dark:text-purple-400" />
                <div>
                  <h3 class="text-xs font-semibold text-ink">Simulador Interativo (Test Drive)</h3>
                  <p class="text-[10px] text-ink-muted">Teste como o bot se comporta antes de ligar no WhatsApp.</p>
                </div>
              </div>
              <button
                type="button"
                class="rounded p-1.5 text-ink-muted transition hover:bg-line hover:text-ink"
                title="Limpar conversa"
                @click="resetSimulator"
              >
                <RotateCcw class="h-3.5 w-3.5" />
              </button>
            </div>

            <!-- Handoff Alert in Simulator -->
            <div
              v-if="simHandoffNote"
              class="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-700 dark:text-amber-300"
            >
              <AlertCircle class="h-4 w-4 shrink-0 text-amber-600" />
              <span>Transbordo Acionado: <strong>{{ simHandoffNote }}</strong></span>
            </div>

            <!-- Simulator Message Feed -->
            <div class="soft-scrollbar flex-1 space-y-3 overflow-y-auto p-4 bg-canvas/50">
              <div
                v-for="(msg, idx) in simMessages"
                :key="idx"
                class="flex flex-col"
                :class="msg.role === 'user' ? 'items-end' : 'items-start'"
              >
                <span class="mb-0.5 text-[10px] font-medium text-ink-muted">
                  {{ msg.role === 'user' ? 'Você (Cliente)' : botName }}
                </span>
                <div
                  class="max-w-[85%] rounded-2xl px-3.5 py-2 text-xs leading-relaxed shadow-sm"
                  :class="
                    msg.role === 'user'
                      ? 'bg-purple-600 text-white'
                      : 'bg-panel text-ink ring-1 ring-line'
                  "
                >
                  {{ msg.content }}
                </div>
              </div>

              <div v-if="simLoading" class="flex items-center gap-2 text-xs text-ink-muted">
                <span class="h-3 w-3 animate-spin rounded-full border-2 border-purple-600 border-t-transparent" />
                <span>{{ botName }} digitando...</span>
              </div>
            </div>

            <!-- Simulator Input -->
            <form class="border-t border-line p-3 flex gap-2" @submit.prevent="handleSimulateSend">
              <input
                v-model="simInput"
                type="text"
                placeholder="Envie uma mensagem de teste..."
                class="h-9 flex-1 rounded-lg border border-line bg-panel px-3 text-xs text-ink outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/15"
                :disabled="simLoading"
              />
              <button
                type="submit"
                class="grid h-9 w-9 place-items-center rounded-lg bg-purple-600 text-white shadow-sm transition hover:bg-purple-700 active:scale-95 disabled:opacity-50"
                :disabled="!simInput.trim() || simLoading"
              >
                <Send class="h-4 w-4" />
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
