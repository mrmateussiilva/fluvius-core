<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  BellRing,
  Check,
  CircleUserRound,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Monitor,
  Moon,
  Palette,
  Play,
  ShieldCheck,
  Sun,
  Volume2,
} from 'lucide-vue-next'
import { useInterfacePreferences } from '../composables/useInterfacePreferences'
import { useTheme, type ThemePreference } from '../composables/useTheme'
import { useAuthStore } from '../stores/authStore'
import { playIncomingMessageSound } from '../utils/sound'

const auth = useAuthStore()
const { preference, setThemePreference } = useTheme()
const { messageSoundEnabled, setMessageSoundEnabled } = useInterfacePreferences()

const profileName = ref('')
const currentPassword = ref('')
const newPassword = ref('')
const passwordConfirmation = ref('')
const profileSaving = ref(false)
const passwordSaving = ref(false)
const profileError = ref('')
const passwordError = ref('')
const profileNotice = ref('')
const passwordNotice = ref('')

const userInitial = computed(
  () => auth.user?.name?.trim().charAt(0).toUpperCase() || 'U',
)
const roleLabel = computed(() =>
  auth.user?.role === 'admin' ? 'Administrador' : 'Atendente',
)
const normalizedProfileName = computed(() => profileName.value.trim().replace(/\s+/g, ' '))
const profileChanged = computed(
  () =>
    normalizedProfileName.value.length >= 2 &&
    normalizedProfileName.value !== auth.user?.name,
)

const themeOptions: Array<{
  value: ThemePreference
  label: string
  description: string
  icon: typeof Sun
}> = [
  {
    value: 'system',
    label: 'Sistema',
    description: 'Acompanha o dispositivo',
    icon: Monitor,
  },
  {
    value: 'light',
    label: 'Claro',
    description: 'Melhor em ambientes claros',
    icon: Sun,
  },
  {
    value: 'dark',
    label: 'Escuro',
    description: 'Mais confortável à noite',
    icon: Moon,
  },
]

async function saveProfile() {
  if (!profileChanged.value) return
  profileSaving.value = true
  profileError.value = ''
  profileNotice.value = ''
  try {
    await auth.updateProfile({ name: normalizedProfileName.value })
    profileName.value = auth.user?.name || normalizedProfileName.value
    profileNotice.value = 'Seu nome de exibição foi atualizado.'
  } catch (exception) {
    profileError.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível atualizar seu perfil'
  } finally {
    profileSaving.value = false
  }
}

async function savePassword() {
  passwordError.value = ''
  passwordNotice.value = ''
  if (newPassword.value.length < 8) {
    passwordError.value = 'A nova senha deve ter pelo menos 8 caracteres.'
    return
  }
  if (newPassword.value !== passwordConfirmation.value) {
    passwordError.value = 'A confirmação não corresponde à nova senha.'
    return
  }

  passwordSaving.value = true
  try {
    await auth.updateProfile({
      current_password: currentPassword.value,
      new_password: newPassword.value,
    })
    currentPassword.value = ''
    newPassword.value = ''
    passwordConfirmation.value = ''
    passwordNotice.value = 'Senha atualizada com segurança.'
  } catch (exception) {
    passwordError.value =
      exception instanceof Error
        ? exception.message
        : 'Não foi possível atualizar sua senha'
  } finally {
    passwordSaving.value = false
  }
}

function toggleMessageSound() {
  setMessageSoundEnabled(!messageSoundEnabled.value)
}

onMounted(async () => {
  await auth.restore()
  profileName.value = auth.user?.name || ''
})
</script>

<template>
  <div class="soft-scrollbar h-full overflow-y-auto">
    <div class="mx-auto max-w-5xl px-4 py-6 sm:px-8 sm:py-8">
      <header class="flex items-center gap-2 text-fluvius-700">
        <CircleUserRound class="h-5 w-5" />
        <span class="text-xs font-semibold uppercase tracking-wider">Minha conta</span>
      </header>
      <h1 class="mt-1 text-2xl font-semibold tracking-tight text-ink">
        Seu posto de atendimento
      </h1>
      <p class="mt-1 max-w-2xl text-sm leading-6 text-ink-muted">
        Ajuste como você aparece para a equipe e deixe a interface confortável para o seu turno.
      </p>

      <section
        class="mt-6 overflow-hidden rounded-xl border border-line bg-panel shadow-sm"
        aria-labelledby="account-summary-title"
      >
        <div class="h-1 bg-fluvius-600" />
        <div class="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div class="flex min-w-0 items-center gap-4">
            <div
              class="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-fluvius-100 text-xl font-semibold text-fluvius-800 dark:bg-fluvius-700/20"
            >
              {{ userInitial }}
            </div>
            <div class="min-w-0">
              <h2 id="account-summary-title" class="truncate text-lg font-semibold text-ink">
                {{ auth.user?.name }}
              </h2>
              <p class="truncate text-sm text-ink-muted">{{ auth.user?.email }}</p>
              <p class="mt-1 truncate text-xs text-ink-faint">
                {{ auth.user?.tenant_name }} · {{ roleLabel }}
              </p>
            </div>
          </div>
          <div
            class="inline-flex w-fit items-center gap-2 rounded-full bg-success-soft px-3 py-1.5 text-xs font-semibold text-success-strong"
          >
            <span class="h-2 w-2 rounded-full bg-success" />
            Acesso ativo
          </div>
        </div>
      </section>

      <div class="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)]">
        <div class="grid gap-5">
          <form
            class="rounded-xl border border-line bg-panel p-5 shadow-sm sm:p-6"
            @submit.prevent="saveProfile"
          >
            <div class="flex items-start gap-3">
              <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-panel-muted text-ink-secondary">
                <CircleUserRound class="h-5 w-5" />
              </span>
              <div>
                <h2 class="font-semibold text-ink">Identidade no atendimento</h2>
                <p class="mt-0.5 text-xs leading-5 text-ink-muted">
                  Este nome identifica você nas conversas e na distribuição da equipe.
                </p>
              </div>
            </div>

            <div class="mt-5 grid gap-4">
              <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
                Nome de exibição
                <input
                  v-model="profileName"
                  required
                  minlength="2"
                  maxlength="160"
                  autocomplete="name"
                  class="rounded-lg border border-line-strong bg-canvas px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
                />
              </label>
              <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
                E-mail de acesso
                <input
                  :value="auth.user?.email"
                  disabled
                  class="cursor-not-allowed rounded-lg border border-line bg-panel-muted px-3 py-2.5 text-sm font-normal text-ink-muted"
                />
                <span class="font-normal text-ink-faint">
                  O e-mail de acesso não pode ser alterado nesta tela.
                </span>
              </label>
            </div>

            <p
              v-if="profileNotice"
              class="mt-4 flex items-center gap-2 rounded-lg bg-success-soft px-3 py-2 text-xs text-success-strong"
            >
              <Check class="h-4 w-4 shrink-0" />
              {{ profileNotice }}
            </p>
            <p
              v-if="profileError"
              class="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger-strong"
            >
              {{ profileError }}
            </p>

            <div class="mt-5 flex justify-end">
              <button
                class="inline-flex min-h-10 min-w-36 items-center justify-center gap-2 rounded-lg bg-fluvius-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-fluvius-800 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!profileChanged || profileSaving"
              >
                <LoaderCircle v-if="profileSaving" class="h-4 w-4 animate-spin" />
                {{ profileSaving ? 'Salvando…' : 'Salvar nome' }}
              </button>
            </div>
          </form>

          <form
            class="rounded-xl border border-line bg-panel p-5 shadow-sm sm:p-6"
            @submit.prevent="savePassword"
          >
            <div class="flex items-start gap-3">
              <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-panel-muted text-ink-secondary">
                <LockKeyhole class="h-5 w-5" />
              </span>
              <div>
                <h2 class="font-semibold text-ink">Segurança da conta</h2>
                <p class="mt-0.5 text-xs leading-5 text-ink-muted">
                  Confirme a senha atual antes de escolher uma nova.
                </p>
              </div>
            </div>

            <div class="mt-5 grid gap-4 sm:grid-cols-2">
              <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary sm:col-span-2">
                Senha atual
                <span class="relative">
                  <KeyRound class="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink-faint" />
                  <input
                    v-model="currentPassword"
                    required
                    type="password"
                    autocomplete="current-password"
                    class="w-full rounded-lg border border-line-strong bg-canvas py-2.5 pl-9 pr-3 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
                  />
                </span>
              </label>
              <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
                Nova senha
                <input
                  v-model="newPassword"
                  required
                  type="password"
                  minlength="8"
                  maxlength="128"
                  autocomplete="new-password"
                  placeholder="Mínimo de 8 caracteres"
                  class="rounded-lg border border-line-strong bg-canvas px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
                />
              </label>
              <label class="grid gap-1.5 text-xs font-semibold text-ink-secondary">
                Confirmar nova senha
                <input
                  v-model="passwordConfirmation"
                  required
                  type="password"
                  minlength="8"
                  maxlength="128"
                  autocomplete="new-password"
                  class="rounded-lg border border-line-strong bg-canvas px-3 py-2.5 text-sm font-normal text-ink outline-none transition focus:border-fluvius-600 focus:ring-2 focus:ring-fluvius-600/20"
                />
              </label>
            </div>

            <p
              v-if="passwordNotice"
              class="mt-4 flex items-center gap-2 rounded-lg bg-success-soft px-3 py-2 text-xs text-success-strong"
            >
              <ShieldCheck class="h-4 w-4 shrink-0" />
              {{ passwordNotice }}
            </p>
            <p
              v-if="passwordError"
              class="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger-strong"
            >
              {{ passwordError }}
            </p>

            <div class="mt-5 flex justify-end">
              <button
                class="inline-flex min-h-10 min-w-36 items-center justify-center gap-2 rounded-lg bg-neutral-action px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 active:scale-[0.97] disabled:opacity-50"
                :disabled="passwordSaving"
              >
                <LoaderCircle v-if="passwordSaving" class="h-4 w-4 animate-spin" />
                {{ passwordSaving ? 'Atualizando…' : 'Trocar senha' }}
              </button>
            </div>
          </form>
        </div>

        <aside class="grid gap-5">
          <section class="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div class="flex items-start gap-3">
              <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-panel-muted text-ink-secondary">
                <Palette class="h-5 w-5" />
              </span>
              <div>
                <h2 class="font-semibold text-ink">Aparência</h2>
                <p class="mt-0.5 text-xs leading-5 text-ink-muted">
                  Escolha o contraste ideal para seu ambiente.
                </p>
              </div>
            </div>

            <div class="mt-4 grid gap-2" role="radiogroup" aria-label="Tema da interface">
              <label
                v-for="option in themeOptions"
                :key="option.value"
                class="flex min-h-14 cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition"
                :class="
                  preference === option.value
                    ? 'border-fluvius-600 bg-fluvius-50'
                    : 'border-line bg-canvas hover:border-line-strong'
                "
              >
                <input
                  class="sr-only"
                  type="radio"
                  name="theme"
                  :value="option.value"
                  :checked="preference === option.value"
                  @change="setThemePreference(option.value)"
                />
                <component
                  :is="option.icon"
                  class="h-5 w-5 shrink-0"
                  :class="preference === option.value ? 'text-fluvius-700' : 'text-ink-muted'"
                />
                <span class="min-w-0 flex-1">
                  <span class="block text-sm font-semibold text-ink">{{ option.label }}</span>
                  <span class="block text-xs text-ink-muted">{{ option.description }}</span>
                </span>
                <span
                  class="grid h-5 w-5 shrink-0 place-items-center rounded-full border"
                  :class="
                    preference === option.value
                      ? 'border-fluvius-600 bg-fluvius-600 text-white'
                      : 'border-line-strong'
                  "
                >
                  <Check v-if="preference === option.value" class="h-3 w-3" />
                </span>
              </label>
            </div>
          </section>

          <section class="rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div class="flex items-start gap-3">
              <span class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-panel-muted text-ink-secondary">
                <BellRing class="h-5 w-5" />
              </span>
              <div>
                <h2 class="font-semibold text-ink">Avisos de atendimento</h2>
                <p class="mt-0.5 text-xs leading-5 text-ink-muted">
                  Controle o alerta de novas mensagens neste navegador.
                </p>
              </div>
            </div>

            <button
              type="button"
              role="switch"
              :aria-checked="messageSoundEnabled"
              class="mt-4 flex min-h-16 w-full items-center gap-3 rounded-lg border border-line bg-canvas px-3 py-3 text-left transition hover:border-line-strong"
              @click="toggleMessageSound"
            >
              <Volume2
                class="h-5 w-5 shrink-0"
                :class="messageSoundEnabled ? 'text-fluvius-700' : 'text-ink-faint'"
              />
              <span class="min-w-0 flex-1">
                <span class="block text-sm font-semibold text-ink">Som de nova mensagem</span>
                <span class="block text-xs text-ink-muted">
                  {{ messageSoundEnabled ? 'Ativado neste navegador' : 'Silenciado neste navegador' }}
                </span>
              </span>
              <span
                class="relative h-6 w-11 shrink-0 rounded-full transition-colors"
                :class="messageSoundEnabled ? 'bg-fluvius-600' : 'bg-disabled'"
                aria-hidden="true"
              >
                <span
                  class="absolute top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform"
                  :class="messageSoundEnabled ? 'translate-x-6' : 'translate-x-1'"
                />
              </span>
            </button>

            <button
              type="button"
              class="mt-3 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-semibold text-ink-secondary transition hover:bg-panel-muted active:scale-[0.97]"
              @click="playIncomingMessageSound(true)"
            >
              <Play class="h-4 w-4" />
              Testar som
            </button>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>
