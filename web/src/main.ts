import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { initializeInterfacePreferences } from './composables/useInterfacePreferences'
import { initializeTheme } from './composables/useTheme'
import { APP_TITLE } from './config/app'
import { router } from './router'
import './styles/main.css'

localStorage.removeItem('fluvius_token')
initializeTheme()
initializeInterfacePreferences()
document.title = APP_TITLE

createApp(App).use(createPinia()).use(router).mount('#app')
