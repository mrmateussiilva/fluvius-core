<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  CheckCircle2,
  KeyRound,
  LoaderCircle,
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
})
const editForm = reactive({
  name: '',
  password: '',
  role: 'agent' as UserRole,
  is_active: true,
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
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">Usuários e acessos</h1>
          <p class="mt-1 max-w-2xl text-sm text-slate-500">
            Cada pessoa entra com seu próprio e-mail e atende somente os canais desta empresa.
          </p>
        </div>
        <button
          v-if="!showCreateForm"
          class="inline-flex items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-fluvius-800"
          @click="showCreateForm = true; error = ''; notice = ''"
        >
          <Plus class="h-4 w-4" />
          Novo usuário
        </button>
      </div>

      <div class="mt-6 grid gap-4 sm:grid-cols-[1fr_auto]">
        <div class="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
          <div class="flex items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-emerald-700 shadow-sm">
              <Smartphone class="h-5 w-5" />
            </span>
            <div class="min-w-0">
              <p class="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                WhatsApp desta empresa
              </p>
              <p class="mt-1 break-words text-sm font-semibold text-emerald-950">
                {{ channelDescription }}
              </p>
              <p class="mt-1 text-xs leading-5 text-emerald-800">
                Os usuários abaixo compartilham as filas desses canais, mantendo atribuição individual por atendimento.
              </p>
            </div>
          </div>
        </div>
        <div class="flex min-w-48 items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <span class="grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-slate-600">
            <UserRound class="h-5 w-5" />
          </span>
          <div>
            <p class="text-2xl font-semibold text-slate-900">{{ activeUsers }}</p>
            <p class="text-xs text-slate-500">usuários ativos</p>
          </div>
        </div>
      </div>

      <div
        v-if="notice"
        class="mt-4 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
      >
        <CheckCircle2 class="h-4 w-4 shrink-0" />
        {{ notice }}
      </div>
      <div
        v-if="error"
        class="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
      >
        {{ error }}
      </div>

      <form
        v-if="showCreateForm"
        class="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
        @submit.prevent="submitCreate"
      >
        <div class="flex items-center justify-between">
          <div>
            <h2 class="font-semibold text-slate-900">Cadastrar usuário</h2>
            <p class="mt-0.5 text-xs text-slate-500">
              O nome será usado para identificar o atendente nas mensagens enviadas.
              Informe também uma senha temporária para o primeiro acesso.
            </p>
          </div>
          <button
            type="button"
            class="rounded-full p-2 text-slate-500 transition hover:bg-slate-100"
            title="Fechar"
            @click="showCreateForm = false"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="mt-4 grid gap-4 md:grid-cols-2">
          <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
            Nome de exibição
            <input
              v-model="createForm.name"
              required
              minlength="2"
              maxlength="160"
              autocomplete="off"
              placeholder="Ex.: Mateus Vendedor"
              class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
            />
          </label>
          <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
            E-mail de acesso
            <input
              v-model="createForm.email"
              required
              type="email"
              maxlength="320"
              autocomplete="off"
              placeholder="atendente@empresa.com"
              class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
            />
          </label>
          <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
            Senha temporária
            <span class="relative">
              <KeyRound class="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
              <input
                v-model="createForm.password"
                required
                type="password"
                minlength="8"
                maxlength="128"
                autocomplete="new-password"
                placeholder="Mínimo de 8 caracteres"
                class="w-full rounded-lg border border-slate-300 py-2.5 pl-9 pr-3 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
              />
            </span>
          </label>
          <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
            Papel
            <select
              v-model="createForm.role"
              class="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-900 outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
            >
              <option value="agent">Atendente</option>
              <option value="admin">Administrador</option>
            </select>
          </label>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button
            type="button"
            class="rounded-lg px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:bg-slate-100"
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

      <div class="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div class="border-b border-slate-100 px-5 py-4">
          <h2 class="font-semibold text-slate-900">Pessoas com acesso</h2>
          <p class="mt-0.5 text-xs text-slate-500">
            Desativar um atendente encerra seu acesso e devolve seus atendimentos abertos para a fila.
          </p>
        </div>
        <div v-if="loading" class="grid min-h-48 place-items-center text-sm text-slate-500">
          <LoaderCircle class="mb-2 h-5 w-5 animate-spin text-fluvius-700" />
          Carregando equipe…
        </div>
        <div v-else-if="!users.length" class="p-8 text-center text-sm text-slate-500">
          Nenhum usuário cadastrado.
        </div>
        <div v-else class="divide-y divide-slate-100">
          <div
            v-for="user in users"
            :key="user.id"
            class="flex flex-col gap-3 px-4 py-4 transition hover:bg-slate-50/70 sm:flex-row sm:items-center sm:px-5"
          >
            <div
              class="grid h-10 w-10 shrink-0 place-items-center rounded-full font-semibold"
              :class="user.is_active ? 'bg-fluvius-100 text-fluvius-800' : 'bg-slate-100 text-slate-400'"
            >
              {{ user.name.trim().charAt(0).toUpperCase() }}
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <p class="truncate font-semibold text-slate-900">{{ user.name }}</p>
                <span
                  v-if="user.id === auth.user?.id"
                  class="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-semibold text-sky-700"
                >
                  Você
                </span>
              </div>
              <p class="truncate text-sm text-slate-500">{{ user.email }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-2 sm:justify-end">
              <span
                class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="
                  user.role === 'admin'
                    ? 'bg-violet-50 text-violet-700'
                    : 'bg-slate-100 text-slate-600'
                "
              >
                <ShieldCheck v-if="user.role === 'admin'" class="h-3.5 w-3.5" />
                {{ roleLabel(user.role) }}
              </span>
              <span
                class="rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="
                  user.is_active
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-rose-50 text-rose-700'
                "
              >
                {{ user.is_active ? 'Ativo' : 'Desativado' }}
              </span>
              <span class="hidden text-xs text-slate-400 lg:inline">
                desde {{ formatDate(user.created_at) }}
              </span>
              <button
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-fluvius-300 hover:bg-fluvius-50 hover:text-fluvius-800"
                @click="openEdit(user)"
              >
                <Pencil class="h-3.5 w-3.5" />
                Gerenciar
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="editingUser"
      class="fixed inset-0 z-40 bg-slate-950/35 backdrop-blur-[1px]"
      aria-hidden="true"
      @click="closeEdit"
    />
    <form
      v-if="editingUser"
      class="fixed left-1/2 top-1/2 z-50 w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white p-5 shadow-2xl"
      role="dialog"
      aria-label="Gerenciar usuário"
      @submit.prevent="submitEdit"
    >
      <div class="flex items-start justify-between">
        <div>
          <h2 class="text-lg font-semibold text-slate-900">Gerenciar usuário</h2>
          <p class="mt-0.5 text-xs text-slate-500">{{ editingUser.email }}</p>
        </div>
        <button
          type="button"
          class="rounded-full p-2 text-slate-500 transition hover:bg-slate-100"
          title="Fechar"
          @click="closeEdit"
        >
          <X class="h-4 w-4" />
        </button>
      </div>
      <div class="mt-5 grid gap-4">
        <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
          Nome de exibição
          <input
            v-model="editForm.name"
            required
            minlength="2"
            maxlength="160"
            class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
          />
        </label>
        <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
          Papel
          <select
            v-model="editForm.role"
            :disabled="editingUser.id === auth.user?.id"
            class="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-900 outline-none disabled:bg-slate-100 disabled:text-slate-500"
          >
            <option value="agent">Atendente</option>
            <option value="admin">Administrador</option>
          </select>
        </label>
        <label class="grid gap-1.5 text-xs font-semibold text-slate-600">
          Nova senha
          <input
            v-model="editForm.password"
            type="password"
            minlength="8"
            maxlength="128"
            autocomplete="new-password"
            placeholder="Deixe vazio para não alterar"
            class="rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-normal text-slate-900 outline-none focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-100"
          />
        </label>
        <label
          class="flex items-center justify-between rounded-xl border border-slate-200 px-3.5 py-3"
          :class="{ 'opacity-60': editingUser.id === auth.user?.id }"
        >
          <span>
            <span class="block text-sm font-semibold text-slate-800">Acesso ativo</span>
            <span class="mt-0.5 block text-xs text-slate-500">
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
        class="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800"
      >
        Os atendimentos abertos deste usuário voltarão para a fila “Novos”.
      </p>
      <p
        v-if="editError"
        class="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700"
      >
        {{ editError }}
      </p>
      <div class="mt-5 flex justify-end gap-2">
        <button
          type="button"
          class="rounded-lg px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:bg-slate-100"
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
