<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Pencil,
  Plus,
  ShieldCheck,
  Smartphone,
  UserRound,
  UsersRound,
  X,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { listChannels } from '../api/channels'
import type { Channel, TenantUser, UserRole } from '../api/types'
import { createUser, listUsers, updateUser } from '../api/users'
import { useAuthStore } from '../stores/authStore'

const auth = useAuthStore()
const router = useRouter()
const users = ref<TenantUser[]>([])
const channels = ref<Channel[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const editError = ref('')
const notice = ref('')
const showCreateForm = ref(false)
const editingUser = ref<TenantUser | null>(null)
const createForm = reactive({
  name: '',
  email: '',
  password: '',
  role: 'agent' as UserRole,
  channel_ids: [] as string[],
})
const editForm = reactive({
  name: '',
  password: '',
  role: 'agent' as UserRole,
  is_active: true,
  channel_ids: [] as string[],
})

const activeUsers = computed(
  () => users.value.filter((user) => user.is_active).length,
)
const channelDescription = computed(() => {
  if (!channels.value.length) return 'Nenhum número cadastrado'
  return channels.value
    .map((channel) => channel.phone_number || channel.name)
    .join(' · ')
})

function roleLabel(role: UserRole) {
  return role === 'admin' ? 'Administrador' : 'Atendente'
}

function userChannelNames(user: TenantUser) {
  if (user.role === 'admin') return 'Todos os canais'
  const names = channels.value
    .filter((channel) => user.channel_ids.includes(channel.id))
    .map((channel) => channel.name)
  return names.length ? names.join(' · ') : 'Sem canal atribuído'
}

function openCreate() {
  Object.assign(createForm, {
    name: '',
    email: '',
    password: '',
    role: 'agent',
    channel_ids: channels.value.map((channel) => channel.id),
  })
  showCreateForm.value = true
  error.value = ''
  notice.value = ''
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value))
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [tenantUsers, tenantChannels] = await Promise.all([
      listUsers(),
      listChannels(),
    ])
    users.value = tenantUsers
    channels.value = tenantChannels
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar a equipe'
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const user = await createUser({ ...createForm })
    users.value.push(user)
    users.value.sort((left, right) => left.name.localeCompare(right.name))
    Object.assign(createForm, {
      name: '',
      email: '',
      password: '',
      role: 'agent',
      channel_ids: [],
    })
    showCreateForm.value = false
    notice.value = `${user.name} já pode entrar com o e-mail e a senha cadastrados.`
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível criar o usuário'
  } finally {
    saving.value = false
  }
}

function openEdit(user: TenantUser) {
  editingUser.value = user
  Object.assign(editForm, {
    name: user.name,
    password: '',
    role: user.role,
    is_active: user.is_active,
    channel_ids: [...user.channel_ids],
  })
  editError.value = ''
  error.value = ''
  notice.value = ''
}

function closeEdit() {
  if (saving.value) return
  editingUser.value = null
}

async function submitEdit() {
  const target = editingUser.value
  if (!target) return
  saving.value = true
  editError.value = ''
  notice.value = ''
  try {
    const updated = await updateUser(target.id, {
      name: editForm.name,
      role: editForm.role,
      is_active: editForm.is_active,
      channel_ids:
        editForm.role === 'agent' ? [...editForm.channel_ids] : [],
      ...(editForm.password ? { password: editForm.password } : {}),
    })
    const index = users.value.findIndex((user) => user.id === updated.id)
    if (index >= 0) users.value[index] = updated
    editingUser.value = null
    notice.value = `Acesso de ${updated.name} atualizado.`
  } catch (exception) {
    editError.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível atualizar o usuário'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await auth.restore()
    if (auth.user?.role !== 'admin') {
      await router.replace('/app/conversations')
      return
    }
    await refresh()
  } catch {
    // The HTTP client handles expired sessions.
  }
})
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto max-w-6xl p-5 sm:p-8">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div class="flex items-center gap-2 text-fluvius-700">
            <UsersRound class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-wider">Equipe da empresa</span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold text-ink">Usuários e acessos</h1>
          <p class="mt-1 max-w-2xl text-sm text-ink-muted">
            Cada pessoa entra com seu próprio e-mail e atende somente os números atribuídos.
          </p>
        </div>
        <button
          v-if="!showCreateForm"
          class="inline-flex items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-fluvius-800"
          @click="openCreate"
        >
          <Plus class="h-4 w-4" />
          Novo usuário
        </button>
      </div>

      <div class="mt-6 grid gap-4 sm:grid-cols-[1fr_auto]">
        <div class="rounded-lg border border-success/30 bg-success-soft p-4">
          <div class="flex items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-panel text-success-strong shadow-sm">
              <Smartphone class="h-5 w-5" />
            </span>
            <div class="min-w-0">
              <p class="text-xs font-semibold uppercase tracking-wide text-success-strong">
                WhatsApp desta empresa
              </p>
              <p class="mt-1 break-words text-sm font-semibold text-success-strong">
                {{ channelDescription }}
              </p>
              <p class="mt-1 text-xs leading-5 text-success-strong">
                Administradores enxergam tudo; cada atendente recebe somente os canais necessários.
              </p>
            </div>
          </div>
        </div>
        <div class="flex min-w-48 items-center gap-3 rounded-lg border border-line bg-panel p-4 shadow-sm">
          <span class="grid h-10 w-10 place-items-center rounded-full bg-panel-muted text-ink-secondary">
            <UserRound class="h-5 w-5" />
          </span>
          <div>
            <p class="text-2xl font-semibold text-ink">{{ activeUsers }}</p>
            <p class="text-xs text-ink-muted">usuários ativos</p>
          </div>
        </div>
      </div>

      <div
        v-if="notice"
        class="mt-4 flex items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-strong"
      >
        <CheckCircle2 class="h-4 w-4 shrink-0" />
        {{ notice }}
      </div>
      <div
        v-if="error"
        class="mt-4 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger-strong"
      >
        {{ error }}
      </div>

      <form
        v-if="showCreateForm"
        class="mt-5 rounded-lg border border-line bg-panel p-5 shadow-sm"
        @submit.prevent="submitCreate"
      >
        <div class="flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-ink">Cadastrar usuário</h2>
            <p class="mt-0.5 text-xs text-ink-muted">
              O nome será usado para identificar o atendente nas mensagens enviadas.
              Informe também uma senha temporária para o primeiro acesso.
            </p>
          </div>
          <button
            type="button"
            class="rounded-full p-2 text-ink-muted transition hover:bg-panel-muted"
            title="Fechar"
            @click="showCreateForm = false"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="mt-4 grid gap-4 md:grid-cols-2">
          <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
            Nome de exibição
            <input
              v-model="createForm.name"
              required
              minlength="2"
              maxlength="160"
              autocomplete="off"
              placeholder="Ex.: Mateus Vendedor"
              class="rounded-lg border border-line-strong px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
            />
          </label>
          <fieldset
            v-if="createForm.role === 'agent'"
            class="grid gap-2 rounded-lg border border-line p-3 md:col-span-2"
          >
            <legend class="px-1 text-xs font-semibold text-ink-secondary">
              Canais permitidos
            </legend>
            <p v-if="!channels.length" class="text-xs text-ink-muted">
              Cadastre um canal do WhatsApp antes de liberar atendimento.
            </p>
            <label
              v-for="channel in channels"
              :key="channel.id"
              class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-ink-secondary hover:bg-canvas"
            >
              <input
                v-model="createForm.channel_ids"
                type="checkbox"
                :value="channel.id"
                class="h-4 w-4 accent-emerald-600"
              />
              <span class="font-medium">{{ channel.name }}</span>
              <span class="text-xs text-ink-faint">
                {{ channel.phone_number || 'Número ainda não identificado' }}
              </span>
            </label>
          </fieldset>
          <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
            E-mail de acesso
            <input
              v-model="createForm.email"
              required
              type="email"
              maxlength="320"
              autocomplete="off"
              placeholder="atendente@empresa.com"
              class="rounded-lg border border-line-strong px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
            />
          </label>
          <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
            Senha temporária
            <span class="relative">
              <KeyRound class="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-faint" />
              <input
                v-model="createForm.password"
                required
                type="password"
                minlength="8"
                maxlength="128"
                autocomplete="new-password"
                placeholder="Mínimo de 8 caracteres"
                class="w-full rounded-lg border border-line-strong py-2.5 pl-9 pr-3 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
              />
            </span>
          </label>
          <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
            Papel
            <select
              v-model="createForm.role"
              class="rounded-lg border border-line-strong bg-panel px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
            >
              <option value="agent">Atendente</option>
              <option value="admin">Administrador</option>
            </select>
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button
            type="button"
            class="rounded-lg px-4 py-2.5 text-sm font-semibold text-ink-secondary transition hover:bg-panel-muted"
            @click="showCreateForm = false"
          >
            Cancelar
          </button>
          <button
            class="inline-flex min-w-36 items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-fluvius-800 disabled:opacity-50"
            :disabled="saving"
          >
            <LoaderCircle v-if="saving" class="h-4 w-4 animate-spin" />
            {{ saving ? 'Cadastrando…' : 'Criar acesso' }}
          </button>
        </div>
      </form>

      <div class="mt-5 overflow-hidden rounded-lg border border-line bg-panel shadow-sm">
        <div class="border-b border-line px-5 py-4">
          <h2 class="font-semibold text-ink">Pessoas com acesso</h2>
          <p class="mt-0.5 text-xs text-ink-muted">
            Desativar um atendente encerra seu acesso e devolve seus atendimentos abertos para a fila.
          </p>
        </div>
        <div v-if="loading" class="grid min-h-48 place-items-center text-sm text-ink-muted">
          <LoaderCircle class="mb-2 h-5 w-5 animate-spin text-fluvius-700" />
          Carregando equipe…
        </div>
        <div v-else-if="!users.length" class="p-8 text-center text-sm text-ink-muted">
          Nenhum usuário cadastrado.
        </div>
        <div v-else class="divide-y divide-line">
          <div
            v-for="user in users"
            :key="user.id"
            class="flex flex-col gap-3 px-4 py-4 transition hover:bg-canvas/70 sm:flex-row sm:items-center sm:px-5"
          >
            <div
              class="grid h-10 w-10 shrink-0 place-items-center rounded-full font-semibold"
              :class="user.is_active ? 'bg-fluvius-100 text-fluvius-800' : 'bg-panel-muted text-ink-faint'"
            >
              {{ user.name.trim().charAt(0).toUpperCase() }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <p class="truncate font-semibold text-ink">{{ user.name }}</p>
                <span
                  v-if="user.id === auth.user?.id"
                  class="rounded-full bg-info-soft px-2 py-0.5 text-[10px] font-semibold text-info-strong"
                >
                  Você
                </span>
                <span
                  v-if="user.is_platform_admin"
                  class="inline-flex items-center gap-1 rounded-full bg-warning-soft px-2 py-0.5 text-[10px] font-semibold text-warning-strong"
                >
                  <LockKeyhole class="h-3 w-3" />
                  Suporte Fluvius
                </span>
              </div>
              <p class="truncate text-sm text-ink-muted">{{ user.email }}</p>
              <p
                class="mt-0.5 truncate text-xs"
                :class="
                  user.role === 'agent' && !user.channel_ids.length
                    ? 'font-medium text-warning'
                    : 'text-ink-faint'
                "
                :title="userChannelNames(user)"
              >
                {{ userChannelNames(user) }}
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-2 sm:justify-end">
              <span
                class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="
                  user.role === 'admin'
                    ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300'
                    : 'bg-panel-muted text-ink-secondary'
                "
              >
                <ShieldCheck v-if="user.role === 'admin'" class="h-3.5 w-3.5" />
                {{ roleLabel(user.role) }}
              </span>
              <span
                class="rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="
                  user.is_active
                    ? 'bg-success-soft text-success-strong'
                    : 'bg-danger-soft text-danger-strong'
                "
              >
                {{ user.is_active ? 'Ativo' : 'Desativado' }}
              </span>
              <span class="hidden text-xs text-ink-faint lg:inline">
                desde {{ formatDate(user.created_at) }}
              </span>
              <button
                v-if="!user.is_platform_admin"
                class="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink-secondary transition hover:border-fluvius-300 hover:bg-fluvius-50 hover:text-fluvius-800"
                @click="openEdit(user)"
              >
                <Pencil class="h-3.5 w-3.5" />
                Gerenciar
              </button>
              <span
                v-else
                class="inline-flex items-center gap-1.5 rounded-lg border border-warning/30 bg-warning-soft px-3 py-1.5 text-xs font-semibold text-warning-strong"
                title="Esta conta só pode ser administrada no plano de controle do Fluvius"
              >
                <LockKeyhole class="h-3.5 w-3.5" />
                Protegida
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="editingUser"
      class="fixed inset-0 z-40 bg-black/35 backdrop-blur-[1px]"
      aria-hidden="true"
      @click="closeEdit"
    />
    <form
      v-if="editingUser"
      class="fixed left-1/2 top-1/2 z-50 w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-panel p-5 shadow-2xl"
      role="dialog"
      aria-label="Gerenciar usuário"
      @submit.prevent="submitEdit"
    >
      <div class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-semibold text-ink">Gerenciar usuário</h2>
          <p class="mt-0.5 text-xs text-ink-muted">{{ editingUser.email }}</p>
        </div>
        <button
          type="button"
          class="rounded-full p-2 text-ink-muted transition hover:bg-panel-muted"
          title="Fechar"
          @click="closeEdit"
        >
          <X class="h-4 w-4" />
        </button>
      </div>
      <div class="mt-5 grid gap-4">
        <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
          Nome de exibição
          <input
            v-model="editForm.name"
            required
            minlength="2"
            maxlength="160"
            class="rounded-lg border border-line-strong px-3 py-2.5 text-sm font-normal text-ink outline-none focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
          />
        </label>
        <fieldset
          v-if="editForm.role === 'agent'"
          class="grid gap-2 rounded-lg border border-line p-3"
        >
          <legend class="px-1 text-xs font-semibold text-ink-secondary">
            Canais permitidos
          </legend>
          <label
            v-for="channel in channels"
            :key="channel.id"
            class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-ink-secondary hover:bg-canvas"
          >
            <input
              v-model="editForm.channel_ids"
              type="checkbox"
              :value="channel.id"
              class="h-4 w-4 accent-emerald-600"
            />
            <span class="font-medium">{{ channel.name }}</span>
            <span class="text-xs text-ink-faint">
              {{ channel.phone_number || 'Número ainda não identificado' }}
            </span>
          </label>
          <p
            v-if="!editForm.channel_ids.length"
            class="rounded-lg bg-warning-soft px-2.5 py-2 text-xs text-warning-strong"
          >
            Sem canais selecionados, o atendente não verá conversas.
          </p>
        </fieldset>
        <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
          Papel
          <select
            v-model="editForm.role"
            :disabled="editingUser.id === auth.user?.id"
            class="rounded-lg border border-line-strong bg-panel px-3 py-2.5 text-sm font-normal text-ink outline-none disabled:bg-panel-muted disabled:text-ink-muted"
          >
            <option value="agent">Atendente</option>
            <option value="admin">Administrador</option>
          </select>
        </label>
        <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
          Nova senha
          <input
            v-model="editForm.password"
            type="password"
            minlength="8"
            maxlength="128"
            autocomplete="new-password"
            placeholder="Deixe vazio para não alterar"
            class="rounded-lg border border-line-strong px-3 py-2.5 text-sm font-normal text-ink outline-none focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
          />
        </label>
        <label
          class="flex items-center justify-between rounded-lg border border-line px-3.5 py-3"
          :class="{ 'opacity-60': editingUser.id === auth.user?.id }"
        >
          <span>
            <span class="block text-sm font-semibold text-ink">Acesso ativo</span>
            <span class="mt-0.5 block text-xs text-ink-muted">
              Permite entrar e assumir atendimentos.
            </span>
          </span>
          <input
            v-model="editForm.is_active"
            type="checkbox"
            :disabled="editingUser.id === auth.user?.id"
            class="h-5 w-5 accent-emerald-600"
          />
        </label>
      </div>
      <p
        v-if="!editForm.is_active"
        class="mt-4 rounded-lg bg-warning-soft px-3 py-2 text-xs leading-5 text-warning-strong"
      >
        Os atendimentos abertos deste usuário voltarão para a fila “Novos”.
      </p>
      <p
        v-if="editError"
        class="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-xs leading-5 text-danger-strong"
      >
        {{ editError }}
      </p>
      <div class="mt-5 flex justify-end gap-2">
        <button
          type="button"
          class="rounded-lg px-4 py-2.5 text-sm font-semibold text-ink-secondary transition hover:bg-panel-muted"
          @click="closeEdit"
        >
          Cancelar
        </button>
        <button
          class="inline-flex min-w-32 items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-fluvius-800 disabled:opacity-50"
          :disabled="saving"
        >
          <LoaderCircle v-if="saving" class="h-4 w-4 animate-spin" />
          {{ saving ? 'Salvando…' : 'Salvar' }}
        </button>
      </div>
    </form>
  </div>
</template>
