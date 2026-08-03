<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  ClipboardCopy,
  ExternalLink,
  KeyRound,
  LoaderCircle,
  Mail,
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
const initialAccess = ref<{
  companyName: string
  loginUrl: string
  email: string
  password: string
} | null>(null)
const accessCopied = ref(false)
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

function tenantLoginUrl(slug: string) {
  return `${window.location.origin}/login/${slug}`
}

async function copyText(value: string, successMessage: string) {
  try {
    await navigator.clipboard.writeText(value)
    error.value = ''
    notice.value = successMessage
  } catch {
    error.value = 'O navegador não permitiu copiar. Selecione o conteúdo manualmente.'
  }
}

async function copyInitialAccess() {
  if (!initialAccess.value) return
  const access = initialAccess.value
  error.value = ''
  await copyText(
    [
      `Acesso Fluvius — ${access.companyName}`,
      `Link: ${access.loginUrl}`,
      `E-mail: ${access.email}`,
      `Senha inicial: ${access.password}`,
    ].join('\n'),
    'Dados de acesso copiados.',
  )
  accessCopied.value = !error.value
}

function closeInitialAccess() {
  initialAccess.value = null
  accessCopied.value = false
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
    const credentials = {
      email: form.admin_email,
      password: form.admin_password,
    }
    const created = await createPlatformTenant({ ...form })
    await loadTenants()
    createOpen.value = false
    initialAccess.value = {
      companyName: created.name,
      loginUrl: tenantLoginUrl(created.slug),
      email: credentials.email,
      password: credentials.password,
    }
    accessCopied.value = false
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
  <div class="h-full overflow-y-auto bg-canvas">
    <div class="mx-auto max-w-7xl p-5 sm:p-8">
      <header class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div class="flex items-center gap-2 text-warning-strong">
            <ShieldCheck class="h-5 w-5" />
            <span class="text-xs font-semibold uppercase tracking-[0.14em]">
              Administração Fluvius
            </span>
          </div>
          <h1 class="mt-1 text-2xl font-semibold text-ink">
            Empresas da plataforma
          </h1>
          <p class="mt-1 max-w-3xl text-sm leading-6 text-ink-muted">
            Crie empresas, acompanhe seus acessos e canais, suspenda operações e
            entre para suporte com registro de auditoria.
          </p>
        </div>
        <div class="flex gap-2">
          <button
            class="inline-flex items-center gap-2 rounded-lg border border-line bg-panel px-4 py-2.5 text-sm font-medium text-ink-secondary hover:bg-canvas"
            :disabled="loading"
            @click="loadTenants"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
            Atualizar
          </button>
          <button
            class="inline-flex items-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-fluvius-800"
            @click="createOpen = true"
          >
            <Plus class="h-4 w-4" />
            Nova empresa
          </button>
        </div>
      </header>

      <div
        class="mt-4 rounded-lg border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning-strong"
      >
        Você está operando em
        <strong>{{ auth.user?.tenant_name }}</strong>. Entrar em outra empresa
        cria um acesso administrativo auditado.
      </div>

      <div
        v-if="notice"
        class="mt-4 flex items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-4 py-3 text-sm text-success-strong"
      >
        <CheckCircle2 class="h-4 w-4" />
        {{ notice }}
      </div>
      <div
        v-if="error"
        class="mt-4 flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger-strong"
      >
        <XCircle class="h-4 w-4" />
        {{ error }}
      </div>

      <section class="mt-6 grid gap-3 sm:grid-cols-3">
        <div class="rounded-lg border border-line bg-panel p-5">
          <p class="text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Empresas
          </p>
          <p class="mt-2 text-3xl font-semibold text-ink">
            {{ tenants.length }}
          </p>
        </div>
        <div class="rounded-lg border border-line bg-panel p-5">
          <p class="text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Ativas
          </p>
          <p class="mt-2 text-3xl font-semibold text-success-strong">
            {{ activeTenants }}
          </p>
        </div>
        <div class="rounded-lg border border-line bg-panel p-5">
          <p class="text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Canais conectados
          </p>
          <p class="mt-2 text-3xl font-semibold text-fluvius-700">
            {{ connectedChannels }}
          </p>
        </div>
      </section>

      <div
        v-if="loading"
        class="mt-6 grid min-h-64 place-items-center rounded-lg border border-line bg-panel"
      >
        <div class="flex items-center gap-2 text-sm text-ink-muted">
          <LoaderCircle class="h-5 w-5 animate-spin text-fluvius-700" />
          Carregando empresas...
        </div>
      </div>

      <div v-else class="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.8fr)]">
        <section class="overflow-hidden rounded-lg border border-line bg-panel">
          <div class="border-b border-line px-5 py-4">
            <h2 class="font-semibold text-ink">Empresas cadastradas</h2>
          </div>
          <div
            v-if="!tenants.length"
            class="grid min-h-48 place-items-center p-8 text-center text-sm text-ink-muted"
          >
            Nenhuma empresa cadastrada.
          </div>
          <div v-else class="divide-y divide-line">
            <article
              v-for="tenant in tenants"
              :key="tenant.id"
              class="grid cursor-pointer gap-4 px-5 py-4 hover:bg-canvas lg:grid-cols-[minmax(0,1fr)_auto]"
              :class="{ 'bg-success-soft/40': selected?.id === tenant.id }"
              @click="selectTenant(tenant.id)"
            >
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="truncate font-semibold text-ink">
                    {{ tenant.name }}
                  </h3>
                  <span
                    class="rounded-full px-2 py-0.5 text-xs font-medium"
                    :class="
                      tenant.is_active
                        ? 'bg-success-soft text-success-strong'
                        : 'bg-panel-muted text-ink-muted'
                    "
                  >
                    {{ tenant.is_active ? 'Ativa' : 'Suspensa' }}
                  </span>
                  <span
                    v-if="tenant.id === auth.user?.tenant_id"
                    class="rounded-full bg-info-soft px-2 py-0.5 text-xs font-medium text-info-strong"
                  >
                    Empresa atual
                  </span>
                </div>
                <p class="mt-1 text-xs text-ink-faint">
                  {{ tenant.slug }} · criada em {{ formatDate(tenant.created_at) }}
                </p>
                <div class="mt-3 flex flex-wrap gap-4 text-xs text-ink-muted">
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
                  class="rounded-lg border border-line px-3 py-2 text-xs font-medium text-ink-secondary hover:bg-canvas disabled:opacity-50"
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

        <aside class="rounded-lg border border-line bg-panel">
          <div class="border-b border-line px-5 py-4">
            <h2 class="font-semibold text-ink">Detalhes da empresa</h2>
          </div>
          <div v-if="detailLoading" class="grid min-h-64 place-items-center">
            <LoaderCircle class="h-6 w-6 animate-spin text-fluvius-700" />
          </div>
          <div
            v-else-if="!selected"
            class="grid min-h-64 place-items-center p-8 text-center text-sm text-ink-muted"
          >
            Selecione uma empresa para ver usuários e canais.
          </div>
          <div v-else class="p-5">
            <div class="flex items-start gap-3">
              <div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-fluvius-50 text-fluvius-700">
                <Building2 class="h-5 w-5" />
              </div>
              <div class="min-w-0">
                <p class="truncate font-semibold text-ink">{{ selected.name }}</p>
                <p class="text-xs text-ink-faint">{{ selected.slug }}</p>
              </div>
            </div>

            <div class="mt-5 rounded-lg border border-fluvius-100 bg-fluvius-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wider text-fluvius-700">
                Link exclusivo de acesso
              </p>
              <p class="mt-1 break-all text-xs text-ink-secondary">
                {{ tenantLoginUrl(selected.slug) }}
              </p>
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded-lg border border-fluvius-200 bg-panel px-3 py-2 text-xs font-medium text-fluvius-800 hover:bg-fluvius-100"
                  @click="
                    copyText(
                      tenantLoginUrl(selected.slug),
                      'Link de acesso copiado.',
                    )
                  "
                >
                  <ClipboardCopy class="h-3.5 w-3.5" />
                  Copiar link
                </button>
                <a
                  :href="tenantLoginUrl(selected.slug)"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-fluvius-800 hover:bg-fluvius-100"
                >
                  <ExternalLink class="h-3.5 w-3.5" />
                  Abrir
                </a>
              </div>
            </div>

            <h3 class="mt-6 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Usuários
            </h3>
            <div v-if="selected.users.length" class="mt-2 space-y-2">
              <div
                v-for="member in selected.users"
                :key="member.id"
                class="flex items-center gap-3 rounded-lg border border-line p-3"
              >
                <UserRound class="h-4 w-4 shrink-0 text-ink-faint" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-ink">
                    {{ member.name }}
                  </p>
                  <p class="truncate text-xs text-ink-faint">{{ member.email }}</p>
                </div>
                <div class="text-right text-xs">
                  <p class="font-medium text-ink-secondary">
                    {{ member.role === 'admin' ? 'Admin' : 'Atendente' }}
                  </p>
                  <p :class="member.is_active ? 'text-success' : 'text-ink-faint'">
                    {{ member.is_active ? 'Ativo' : 'Inativo' }}
                  </p>
                </div>
              </div>
            </div>
            <p v-else class="mt-2 text-sm text-ink-faint">Nenhum usuário.</p>

            <h3 class="mt-6 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Canais
            </h3>
            <div v-if="selected.channels.length" class="mt-2 space-y-2">
              <div
                v-for="channel in selected.channels"
                :key="channel.id"
                class="flex items-center gap-3 rounded-lg border border-line p-3"
              >
                <Smartphone class="h-4 w-4 shrink-0 text-ink-faint" />
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-medium text-ink">
                    {{ channel.name }}
                  </p>
                  <p class="truncate text-xs text-ink-faint">
                    {{ channel.phone_number || 'Número ainda não identificado' }}
                  </p>
                </div>
                <ChannelStatusBadge :status="channel.status" />
              </div>
            </div>
            <p v-else class="mt-2 text-sm text-ink-faint">Nenhum canal.</p>
          </div>
        </aside>
      </div>
    </div>

    <div
      v-if="createOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4"
      @click.self="createOpen = false"
    >
      <form
        class="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-lg bg-panel p-6 shadow-2xl"
        @submit.prevent="submitTenant"
      >
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-xl font-semibold text-ink">Nova empresa</h2>
            <p class="mt-1 text-sm text-ink-muted">
              A empresa e seu primeiro administrador serão criados juntos.
            </p>
          </div>
          <button
            type="button"
            class="rounded-lg p-2 text-ink-faint hover:bg-panel-muted"
            @click="createOpen = false"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="mt-5 grid gap-4 sm:grid-cols-2">
          <label class="text-sm font-medium text-ink-secondary">
            Nome da empresa
            <input
              v-model="form.name"
              required
              minlength="2"
              maxlength="160"
              class="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="Empresa Exemplo"
            />
          </label>
          <label class="text-sm font-medium text-ink-secondary">
            Identificador
            <input
              v-model="form.slug"
              required
              minlength="2"
              maxlength="100"
              pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
              class="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="empresa-exemplo"
              @blur="normalizeSlug"
            />
          </label>
          <label class="text-sm font-medium text-ink-secondary">
            Administrador inicial
            <input
              v-model="form.admin_name"
              required
              minlength="2"
              maxlength="160"
              class="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="Nome do administrador"
            />
          </label>
          <label class="text-sm font-medium text-ink-secondary">
            E-mail
            <input
              v-model="form.admin_email"
              type="email"
              required
              class="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="admin@empresa.com.br"
            />
          </label>
          <label class="text-sm font-medium text-ink-secondary sm:col-span-2">
            Senha inicial
            <input
              v-model="form.admin_password"
              type="password"
              required
              minlength="12"
              maxlength="128"
              autocomplete="new-password"
              class="mt-1.5 w-full rounded-lg border border-line-strong px-3 py-2.5 outline-none focus:border-fluvius-600"
              placeholder="No mínimo 12 caracteres"
            />
          </label>
        </div>

        <div class="mt-6 flex justify-end gap-2">
          <button
            type="button"
            class="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink-secondary hover:bg-canvas"
            @click="createOpen = false"
          >
            Cancelar
          </button>
          <button
            class="inline-flex items-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-fluvius-800 disabled:opacity-50"
            :disabled="creating"
          >
            <LoaderCircle v-if="creating" class="h-4 w-4 animate-spin" />
            <Plus v-else class="h-4 w-4" />
            Criar empresa
          </button>
        </div>
      </form>
    </div>

    <div
      v-if="initialAccess"
      class="fixed inset-0 z-[60] grid place-items-center bg-black/55 p-4"
      @click.self="closeInitialAccess"
    >
      <section class="w-full max-w-lg rounded-lg bg-panel p-6 shadow-2xl">
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="flex items-center gap-2 text-success-strong">
              <CheckCircle2 class="h-5 w-5" />
              <span class="text-xs font-semibold uppercase tracking-wider">
                Empresa criada
              </span>
            </div>
            <h2 class="mt-1 text-xl font-semibold text-ink">
              Envie este acesso ao cliente
            </h2>
            <p class="mt-1 text-sm leading-6 text-ink-muted">
              A senha é exibida somente agora. Depois de fechar, ela não poderá
              ser consultada nesta tela.
            </p>
          </div>
          <button
            type="button"
            class="rounded-lg p-2 text-ink-faint hover:bg-panel-muted"
            aria-label="Fechar"
            @click="closeInitialAccess"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <dl class="mt-5 space-y-3">
          <div class="rounded-lg border border-line p-3">
            <dt class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              <ExternalLink class="h-3.5 w-3.5" />
              Link da empresa
            </dt>
            <dd class="mt-1 break-all text-sm font-medium text-ink">
              {{ initialAccess.loginUrl }}
            </dd>
          </div>
          <div class="rounded-lg border border-line p-3">
            <dt class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              <Mail class="h-3.5 w-3.5" />
              E-mail
            </dt>
            <dd class="mt-1 break-all text-sm font-medium text-ink">
              {{ initialAccess.email }}
            </dd>
          </div>
          <div class="rounded-lg border border-warning/30 bg-warning-soft p-3">
            <dt class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-warning-strong">
              <KeyRound class="h-3.5 w-3.5" />
              Senha inicial
            </dt>
            <dd class="mt-1 break-all font-mono text-sm font-semibold text-warning-strong">
              {{ initialAccess.password }}
            </dd>
          </div>
        </dl>

        <div class="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink-secondary hover:bg-canvas"
            @click="closeInitialAccess"
          >
            Fechar
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-fluvius-800"
            @click="copyInitialAccess"
          >
            <CheckCircle2 v-if="accessCopied" class="h-4 w-4" />
            <ClipboardCopy v-else class="h-4 w-4" />
            {{ accessCopied ? 'Acesso copiado' : 'Copiar acesso completo' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
