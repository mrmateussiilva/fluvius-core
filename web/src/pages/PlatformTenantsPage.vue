<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  UserRound,
  UsersRound,
  X,
  XCircle,
} from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import {
  accessPlatformTenant,
  createPlatformTenant,
  getPlatformTenant,
  listPlatformTenants,
  updatePlatformTenant,
} from '../api/platform'
import type { PlatformTenant, PlatformTenantDetail } from '../api/types'
import ChannelStatusBadge from '../components/ChannelStatusBadge.vue'
import { useAuthStore } from '../stores/authStore'
import { useRealtimeStore } from '../stores/realtimeStore'

const auth = useAuthStore()
const realtime = useRealtimeStore()
const router = useRouter()
const tenants = ref<PlatformTenant[]>([])
const selected = ref<PlatformTenantDetail | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const createOpen = ref(false)
const creating = ref(false)
const actionTenantId = ref<string | null>(null)
const error = ref('')
const notice = ref('')
const form = reactive({
  name: '',
  slug: '',
  admin_name: '',
  admin_email: '',
  admin_password: '',
})

const activeTenants = computed(
  () => tenants.value.filter((tenant) => tenant.is_active).length,
)
const connectedChannels = computed(
  () =>
    tenants.value.reduce(
      (total, tenant) => total + tenant.connected_channel_count,
      0,
    ),
)

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value))
}

function normalizeSlug() {
  form.slug = form.slug
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

function resetForm() {
  Object.assign(form, {
    name: '',
    slug: '',
    admin_name: '',
    admin_email: '',
    admin_password: '',
  })
}

async function loadTenants() {
  loading.value = true
  error.value = ''
  try {
    tenants.value = await listPlatformTenants()
    if (
      selected.value &&
      !tenants.value.some((tenant) => tenant.id === selected.value?.id)
    ) {
      selected.value = null
    }
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar as empresas'
  } finally {
    loading.value = false
  }
}

async function selectTenant(tenantId: string) {
  detailLoading.value = true
  error.value = ''
  try {
    selected.value = await getPlatformTenant(tenantId)
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível carregar a empresa'
  } finally {
    detailLoading.value = false
  }
}

async function submitTenant() {
  if (creating.value) return
  creating.value = true
  error.value = ''
  notice.value = ''
  normalizeSlug()
  try {
    const created = await createPlatformTenant({ ...form })
    await loadTenants()
    createOpen.value = false
    resetForm()
    notice.value = `${created.name} foi criada com o administrador inicial.`
    await selectTenant(created.id)
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível criar a empresa'
  } finally {
    creating.value = false
  }
}

async function toggleTenant(tenant: PlatformTenant) {
  if (actionTenantId.value) return
  const nextActive = !tenant.is_active
  if (
    !nextActive &&
    !window.confirm(
      `Suspender ${tenant.name}? Usuários e WebSockets perderão o acesso imediatamente.`,
    )
  ) {
    return
  }
  actionTenantId.value = tenant.id
  error.value = ''
  notice.value = ''
  try {
    const updated = await updatePlatformTenant(tenant.id, nextActive)
    const index = tenants.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) tenants.value[index] = updated
    if (selected.value?.id === tenant.id) await selectTenant(tenant.id)
    notice.value = nextActive
      ? `${tenant.name} foi ativada.`
      : `${tenant.name} foi suspensa.`
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível alterar a empresa'
  } finally {
    actionTenantId.value = null
  }
}

async function enterTenant(tenant: PlatformTenant) {
  if (actionTenantId.value || tenant.id === auth.user?.tenant_id) {
    if (tenant.id === auth.user?.tenant_id) {
      await router.push('/app/conversations')
    }
    return
  }
  actionTenantId.value = tenant.id
  error.value = ''
  realtime.disconnect()
  try {
    await accessPlatformTenant(tenant.id)
    await auth.refresh()
    window.location.replace('/app/conversations')
  } catch (exception) {
    error.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível acessar a empresa'
    realtime.connect()
    actionTenantId.value = null
  }
}

onMounted(async () => {
  await auth.restore()
  if (!auth.user?.is_platform_admin) {
    await router.replace('/app/conversations')
    return
  }
  await loadTenants()
})
</script>

<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="mx-auto max-w-7xl p-5 sm:p-8">
      <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div class="flex items-center gap-2 text-amber-700">
            <ShieldCheck class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Administração Fluvius
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold text-slate-900">
            Empresas da plataforma
          </h1>
          <p class="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            Crie empresas, acompanhe seus acessos e canais, suspenda operações e
            entre para suporte com registro de auditoria.
          </p>
        </div>
        <div class="flex gap-2">
          <button
            class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            :disabled="loading"
            @click="loadTenants"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
            Atualizar
          </button>
          <button
            class="inline-flex items-center gap-2 rounded-xl bg-fluvius-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-fluvius-800"
            @click="createOpen = true"
          >
            <Plus class="h-4 w-4" />
            Nova empresa
          </button>
        </div>
      </header>

      <div
        class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
      >
        Você está operando em
        <strong>{{ auth.user?.tenant_name }}</strong>. Entrar em outra empresa
        cria um acesso administrativo auditado.
      </div>

      <div
        v-if="notice"
        class="mt-4 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
      >
        <CheckCircle2 class="h-4 w-4" />
        {{ notice }}
      </div>
      <div
        v-if="error"
        class="mt-4 flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
      >
        <XCircle class="h-4 w-4" />
        {{ error }}
      </div>

      <section class="mt-6 grid gap-3 sm:grid-cols-3">
        <div class="rounded-2xl border border-slate-200 bg-white p-5">
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Empresas
          </p>
          <p class="mt-2 text-3xl font-semibold text-slate-900">
            {{ tenants.length }}
          </p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-5">
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Ativas
          </p>
          <p class="mt-2 text-3xl font-semibold text-emerald-700">
            {{ activeTenants }}
          </p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-5">
          <p class="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Canais conectados
          </p>
          <p class="mt-2 text-3xl font-semibold text-fluvius-700">
            {{ connectedChannels }}
          </p>
        </div>
      </section>

      <div
        v-if="loading"
        class="mt-6 grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"
      >
        <div class="flex items-center gap-2 text-sm text-slate-500">
          <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
          Carregando empresas...
        </div>
      </div>

      <div v-else class="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.8fr)]">
        <section class="overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <div class="border-b border-slate-100 px-5 py-4">
            <h2 class="font-semibold text-slate-900">Empresas cadastradas</h2>
          </div>
          <div
            v-if="!tenants.length"
            class="grid min-h-48 place-items-center p-8 text-center text-sm text-slate-500"
          >
            Nenhuma empresa cadastrada.
          </div>
          <div v-else class="divide-y divide-slate-100">
            <article
              v-for="tenant in tenants"
              :key="tenant.id"
              class="grid cursor-pointer gap-4 px-5 py-4 hover:bg-slate-50 lg:grid-cols-[minmax(0,1fr)_auto]"
              :class="{ 'bg-emerald-50/40': selected?.id === tenant.id }"
              @click="selectTenant(tenant.id)"
            >
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="truncate font-semibold text-slate-900">
                    {{ tenant.name }}
                  </h3>
                  <span
                    class="rounded-full px-2 py-0.5 text-xs font-medium"
                    :class="
                      tenant.is_active
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-slate-100 text-slate-500'
                    "
                  >
                    {{ tenant.is_active ? 'Ativa' : 'Suspensa' }}
                  </span>
                  <span
                    v-if="tenant.id === auth.user?.tenant_id"
                    class="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700"
                  >
                    Empresa atual
                  </span>
                </div>
                <p class="mt-1 text-xs text-slate-400">
                  {{ tenant.slug }} · criada em {{ formatDate(tenant.created_at) }}
                </p>
                <div class="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
                  <span class="inline-flex items-center gap-1">
                    <UsersRound class="h-3.5 w-3.5" />
                    {{ tenant.active_user_count }}/{{ tenant.user_count }} usuários
                  </span>
                  <span class="inline-flex items-center gap-1">
                    <Smartphone class="h-3.5 w-3.5" />
                    {{ tenant.connected_channel_count }}/{{ tenant.channel_count }} canais
                  </span>
                </div>
              </div>
              <div class="flex items-center gap-2" @click.stop>
                <button
                  class="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  :disabled="
                    actionTenantId === tenant.id ||
                    (!tenant.is_active && tenant.id === auth.user?.tenant_id)
                  "
                  @click="toggleTenant(tenant)"
                >
                  {{ tenant.is_active ? 'Suspender' : 'Ativar' }}
                </button>
                <button
                  class="inline-flex items-center gap-1 rounded-lg bg-fluvius-700 px-3 py-2 text-xs font-medium text-white hover:bg-fluvius-800 disabled:opacity-50"
                  :disabled="!tenant.is_active || actionTenantId === tenant.id"
                  @click="enterTenant(tenant)"
                >
                  {{
                    tenant.id === auth.user?.tenant_id
                      ? 'Abrir'
                      : 'Acessar'
                  }}
                  <ArrowRight class="h-3.5 w-3.5" />
                </button>
              </div>
            </article>
          </div>
        </section>

        <aside class="rounded-2xl border border-slate-200 bg-white">
          <div class="border-b border-slate-100 px-5 py-4">
            <h2 class="font-semibold text-slate-900">Detalhes da empresa</h2>
          </div>
          <div v-if="detailLoading" class="grid min-h-64 place-items-center">
            <LoaderCircle class="h-6 w-6 animate-spin text-fluvius-700" />
          </div>
          <div
            v-else-if="!selected"
            class="grid min-h-64 place-items-center p-8 text-center text-sm text-slate-500"
          >
            Selecione uma empresa para ver usuários e canais.
          </div>
          <div v-else class="p-5">
            <div class="flex items-start gap-3">
              <div class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-fluvius-50 text-fluvius-700">
                <Building2 class="h-5 w-5" />
              </div>
              <div class="min-w-0">
                <p class="truncate font-semibold text-slate-900">{{ selected.name }}</p>
                <p class="text-xs text-slate-400">{{ selected.slug }}</p>
              </div>
            </div>

            <h3 class="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-400">
              Usuários
            </h3>
            <div v-if="selected.users.length" class="mt-2 space-y-2">
              <div
                v-for="member in selected.users"
                :key="member.id"
                class="flex items-center gap-3 rounded-xl border border-slate-100 p-3"
              >
                <UserRound class="h-4 w-4 shrink-0 text-slate-400" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-slate-800">
                    {{ member.name }}
                  </p>
                  <p class="truncate text-xs text-slate-400">{{ member.email }}</p>
                </div>
                <div class="text-right text-xs">
                  <p class="font-medium text-slate-600">
                    {{ member.role === 'admin' ? 'Admin' : 'Atendente' }}
                  </p>
                  <p :class="member.is_active ? 'text-emerald-600' : 'text-slate-400'">
                    {{ member.is_active ? 'Ativo' : 'Inativo' }}
                  </p>
                </div>
              </div>
            </div>
            <p v-else class="mt-2 text-sm text-slate-400">Nenhum usuário.</p>

            <h3 class="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-400">
              Canais
            </h3>
            <div v-if="selected.channels.length" class="mt-2 space-y-2">
              <div
                v-for="channel in selected.channels"
                :key="channel.id"
                class="flex items-center gap-3 rounded-xl border border-slate-100 p-3"
              >
                <Smartphone class="h-4 w-4 shrink-0 text-slate-400" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-slate-800">
                    {{ channel.name }}
                  </p>
                  <p class="truncate text-xs text-slate-400">
                    {{ channel.phone_number || 'Número ainda não identificado' }}
                  </p>
                </div>
                <ChannelStatusBadge :status="channel.status" />
              </div>
            </div>
            <p v-else class="mt-2 text-sm text-slate-400">Nenhum canal.</p>
          </div>
        </aside>
      </div>
    </div>

    <div
      v-if="createOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 p-4"
      @click.self="createOpen = false"
    >
      <form
        class="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl"
        @submit.prevent="submitTenant"
      >
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-xl font-semibold text-slate-900">Nova empresa</h2>
            <p class="mt-1 text-sm text-slate-500">
              A empresa e seu primeiro administrador serão criados juntos.
            </p>
          </div>
          <button
            type="button"
            class="rounded-lg p-2 text-slate-400 hover:bg-slate-100"
            @click="createOpen = false"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="mt-5 grid gap-4 sm:grid-cols-2">
          <label class="text-sm font-medium text-slate-700">
            Nome da empresa
            <input
              v-model="form.name"
              required
              minlength="2"
              maxlength="160"
              class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="Empresa Exemplo"
            />
          </label>
          <label class="text-sm font-medium text-slate-700">
            Identificador
            <input
              v-model="form.slug"
              required
              minlength="2"
              maxlength="100"
              pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
              class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="empresa-exemplo"
              @blur="normalizeSlug"
            />
          </label>
          <label class="text-sm font-medium text-slate-700">
            Administrador inicial
            <input
              v-model="form.admin_name"
              required
              minlength="2"
              maxlength="160"
              class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="Nome do administrador"
            />
          </label>
          <label class="text-sm font-medium text-slate-700">
            E-mail
            <input
              v-model="form.admin_email"
              type="email"
              required
              class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="admin@empresa.com.br"
            />
          </label>
          <label class="text-sm font-medium text-slate-700 sm:col-span-2">
            Senha inicial
            <input
              v-model="form.admin_password"
              type="password"
              required
              minlength="12"
              maxlength="128"
              autocomplete="new-password"
              class="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="No mínimo 12 caracteres"
            />
          </label>
        </div>

        <div class="mt-6 flex justify-end gap-2">
          <button
            type="button"
            class="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
            @click="createOpen = false"
          >
            Cancelar
          </button>
          <button
            class="inline-flex items-center gap-2 rounded-xl bg-fluvius-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-fluvius-800 disabled:opacity-50"
            :disabled="creating"
          >
            <LoaderCircle v-if="creating" class="h-4 w-4 animate-spin" />
            <Plus v-else class="h-4 w-4" />
            Criar empresa
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
