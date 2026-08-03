import { computed, readonly, ref } from 'vue'

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = Exclude<ThemePreference, 'system'>

const STORAGE_KEY = 'fluvius_theme'
const preference = ref<ThemePreference>('system')
const systemTheme = ref<ResolvedTheme>('light')
let initialized = false

const resolvedTheme = computed<ResolvedTheme>(() =>
  preference.value === 'system' ? systemTheme.value : preference.value,
)

function isThemePreference(value: string | null): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

function applyTheme() {
  const root = document.documentElement
  root.classList.toggle('dark', resolvedTheme.value === 'dark')
  root.dataset.theme = resolvedTheme.value
  root.dataset.themePreference = preference.value
}

function handleSystemThemeChange(event: MediaQueryListEvent) {
  systemTheme.value = event.matches ? 'dark' : 'light'
  if (preference.value === 'system') applyTheme()
}

export function initializeTheme() {
  if (initialized) return

  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  systemTheme.value = mediaQuery.matches ? 'dark' : 'light'

  const storedPreference = localStorage.getItem(STORAGE_KEY)
  preference.value = isThemePreference(storedPreference) ? storedPreference : 'system'

  mediaQuery.addEventListener('change', handleSystemThemeChange)
  initialized = true
  applyTheme()
}

export function useTheme() {
  function setThemePreference(value: ThemePreference) {
    preference.value = value
    localStorage.setItem(STORAGE_KEY, value)
    applyTheme()
  }

  return {
    preference: readonly(preference),
    resolvedTheme: readonly(resolvedTheme),
    setThemePreference,
  }
}
