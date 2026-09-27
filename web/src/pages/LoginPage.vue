<script setup lang="ts">
import {
  AlertCircle,
  Building2,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
  MessageCircle,
  UserCheck,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTenantLogin } from '../api/auth'
import type { TenantLogin } from '../api/auth'
import { APP_NAME, APP_VERSION } from '../config/app'
import ThemeMenu from '../components/ThemeMenu.vue'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { useAuthStore } from '../stores/authStore'

const email = ref('')
const password = ref('')
const showPassword = ref(false)
const route = useRoute()
const tenant = ref<TenantLogin | null>(null)
const tenantLoading = ref(false)
const tenantUnavailable = ref(false)
const tenantSlug = computed(() => {
  const value = route.params.tenantSlug
  return typeof value === 'string' ? value : undefined
})
const error = ref(
  route.query.session === 'expired' ? 'Sua sessão expirou. Entre novamente.' : '',
)
const auth = useAuthStore()
const router = useRouter()
const canSubmit = computed(
  () =>
    !auth.loading &&
    !tenantLoading.value &&
    !tenantUnavailable.value &&
    email.value.trim().length > 0 &&
    password.value.length > 0,
)

onMounted(async () => {
  if (!tenantSlug.value) return
  tenantLoading.value = true
  try {
    tenant.value = await getTenantLogin(tenantSlug.value)
  } catch {
    tenantUnavailable.value = true
    error.value = 'Este acesso não está disponível. Confirme o link com o administrador.'
  } finally {
    tenantLoading.value = false
  }
})

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  try {
    await auth.signIn(email.value.trim(), password.value, tenantSlug.value)
    router.push('/app/conversations')
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : 'Não foi possível entrar'
  }
}
</script>

<template>
  <main class="relative grid min-h-screen bg-canvas text-ink lg:grid-cols-[minmax(0,1.05fr)_minmax(460px,0.95fr)]">
    <div class="absolute right-4 top-4 z-10 sm:right-6 sm:top-6">
      <ThemeMenu />
    </div>

    <section class="hidden min-h-screen border-r border-line bg-chat px-10 py-10 lg:flex">
      <div class="flex w-full flex-col justify-between">
        <div class="flex items-center gap-3">
          <div class="grid h-12 w-12 shrink-0 place-items-center rounded-lg bg-fluvius-700 text-lg font-bold text-white shadow-sm shadow-fluvius-900/20">
            F
          </div>
          <div>
            <p class="text-lg font-semibold leading-tight text-ink">{{ APP_NAME }}</p>
            <p class="text-xs font-medium text-ink-muted">Mesa de atendimento WhatsApp-first</p>
          </div>
        </div>

        <div class="mx-auto w-full max-w-xl">
          <div class="mb-5 flex items-end justify-between gap-6">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.16em] text-fluvius-700 dark:text-success-strong">
                Operação agora
              </p>
              <h1 class="mt-3 max-w-md text-4xl font-semibold leading-tight text-ink">
                Entre direto na fila que precisa de atenção.
              </h1>
            </div>
            <Badge class="border-fluvius-600/20 bg-fluvius-50 text-fluvius-800 dark:bg-success-soft dark:text-success-strong">
              pronto
            </Badge>
          </div>

          <div class="rounded-xl border border-line bg-panel/92 p-4 shadow-xl shadow-scrim/30 backdrop-blur">
            <div class="flex items-center justify-between border-b border-line pb-3">
              <div>
                <p class="text-sm font-semibold text-ink">Fila não atendidas</p>
                <p class="text-xs text-ink-muted">Novas conversas e retornos do cliente</p>
              </div>
              <Badge variant="secondary" class="bg-warning-soft text-warning-strong">
                3 aguardando
              </Badge>
            </div>

            <div class="mt-4 space-y-3">
              <div class="rounded-lg border border-line bg-canvas p-3">
                <div class="flex items-start gap-3">
                  <div class="grid h-9 w-9 place-items-center rounded-lg bg-success-soft text-success">
                    <MessageCircle class="h-4 w-4" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between gap-3">
                      <p class="truncate text-sm font-semibold text-ink">Cliente novo</p>
                      <span class="text-[11px] font-medium text-ink-faint">agora</span>
                    </div>
                    <p class="mt-1 truncate text-xs text-ink-muted">
                      Preciso falar com alguém sobre meu pedido.
                    </p>
                  </div>
                </div>
              </div>

              <div class="rounded-lg border border-line bg-panel p-3">
                <div class="flex items-start gap-3">
                  <div class="grid h-9 w-9 place-items-center rounded-lg bg-info-soft text-info">
                    <UserCheck class="h-4 w-4" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between gap-3">
                      <p class="truncate text-sm font-semibold text-ink">Atendimento assumido</p>
                      <span class="text-[11px] font-medium text-ink-faint">2 min</span>
                    </div>
                    <p class="mt-1 truncate text-xs text-ink-muted">
                      Última mensagem do cliente voltou para prioridade.
                    </p>
                  </div>
                </div>
              </div>

              <div class="rounded-lg border border-line bg-message-out/70 p-3 dark:bg-message-out/45">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <p class="text-sm font-semibold text-ink">Resposta em revisão</p>
                    <p class="mt-1 text-xs text-ink-muted">Operador confirma antes de enviar</p>
                  </div>
                  <span class="rounded-md bg-panel px-2 py-1 text-[11px] font-semibold text-fluvius-800 dark:text-success-strong">
                    pendente
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <p class="max-w-md text-sm leading-6 text-ink-muted">
          Atendimento, canais e equipe em um fluxo único, com envio bloqueado quando o canal está offline.
        </p>
      </div>
    </section>

    <section class="flex min-h-screen items-center justify-center px-4 py-8 sm:px-6 lg:px-12">
      <Card class="w-full max-w-md border-line bg-panel shadow-xl shadow-scrim/25">
        <CardHeader class="space-y-7 p-6 pb-0 sm:p-8 sm:pb-0">
          <div class="flex items-center gap-3 lg:hidden">
            <div class="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-fluvius-700 font-bold text-white">
              F
            </div>
            <div class="min-w-0">
              <p class="truncate text-lg font-semibold text-ink">{{ APP_NAME }}</p>
              <p class="text-xs text-ink-muted">Atendimento em tempo real</p>
            </div>
          </div>

          <div>
            <CardTitle class="text-2xl font-semibold text-ink">Entrar</CardTitle>
            <CardDescription class="mt-1.5 text-sm text-ink-muted">
              Use suas credenciais para acessar os atendimentos.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent class="p-6 pt-7 sm:p-8 sm:pt-7">
          <div
            v-if="tenantLoading"
            class="mb-5 flex items-center gap-2.5 rounded-lg border border-line bg-panel-muted px-3.5 py-3 text-sm text-ink-secondary"
          >
            <LoaderCircle class="h-4 w-4 animate-spin text-fluvius-600" />
            Validando empresa...
          </div>
          <div
            v-else-if="tenant"
            class="mb-5 flex items-center gap-2.5 rounded-lg border border-fluvius-600/25 bg-fluvius-50 px-3.5 py-3 text-sm text-fluvius-800 dark:bg-success-soft dark:text-success-strong"
          >
            <Building2 class="h-4 w-4 shrink-0 text-fluvius-600" />
            <span>
              Acesso exclusivo de <strong class="font-semibold">{{ tenant.name }}</strong>
            </span>
          </div>
          <div
            v-else-if="tenantUnavailable"
            class="mb-5 flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm text-danger-strong"
          >
            <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>Empresa indisponível ou link inválido.</span>
          </div>

          <form class="space-y-4" @submit.prevent="submit">
            <div>
              <Label for="login-email" class="mb-1.5 block text-sm font-medium text-ink-secondary">
                E-mail
              </Label>
              <div class="relative">
                <Mail
                  class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                />
                <Input
                  id="login-email"
                  v-model="email"
                  type="email"
                  required
                  autocomplete="username"
                  placeholder="voce@empresa.com"
                  :disabled="tenantUnavailable || tenantLoading"
                  class="h-11 border-line-strong bg-canvas pl-10 pr-3 text-ink placeholder:text-ink-faint focus-visible:ring-fluvius-600/15 disabled:bg-panel-muted disabled:text-ink-faint"
                />
              </div>
            </div>

            <div>
              <Label for="login-password" class="mb-1.5 block text-sm font-medium text-ink-secondary">
                Senha
              </Label>
              <div class="relative">
                <Lock
                  class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                />
                <Input
                  id="login-password"
                  v-model="password"
                  :type="showPassword ? 'text' : 'password'"
                  required
                  autocomplete="current-password"
                  placeholder="••••••••"
                  :disabled="tenantUnavailable || tenantLoading"
                  class="h-11 border-line-strong bg-canvas pl-10 pr-11 text-ink placeholder:text-ink-faint focus-visible:ring-fluvius-600/15 disabled:bg-panel-muted disabled:text-ink-faint"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  class="absolute right-2 top-1/2 -translate-y-1/2 text-ink-faint hover:bg-panel-muted hover:text-ink-secondary"
                  :aria-label="showPassword ? 'Ocultar senha' : 'Mostrar senha'"
                  :disabled="tenantUnavailable || tenantLoading"
                  @click="showPassword = !showPassword"
                >
                  <EyeOff v-if="showPassword" class="h-4 w-4" />
                  <Eye v-else class="h-4 w-4" />
                </Button>
              </div>
            </div>

            <div
              v-if="error"
              class="flex items-start gap-2.5 rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm text-danger-strong"
              role="alert"
            >
              <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
              <span>{{ error }}</span>
            </div>

            <Button
              type="submit"
              class="mt-2 h-12 w-full bg-fluvius-700 font-semibold text-white hover:bg-fluvius-800 focus-visible:ring-fluvius-600/25 active:scale-[0.98]"
              :disabled="!canSubmit"
            >
              <LoaderCircle v-if="auth.loading" class="h-4 w-4 animate-spin" />
              {{ auth.loading ? 'Entrando...' : 'Entrar' }}
            </Button>
          </form>

          <p class="mt-8 text-center text-xs text-ink-faint">
            Problemas para entrar? Fale com o administrador da sua empresa.
          </p>
          <p class="mt-4 text-center text-[11px] text-ink-faint">v{{ APP_VERSION }}</p>
        </CardContent>
      </Card>
    </section>
  </main>
</template>
