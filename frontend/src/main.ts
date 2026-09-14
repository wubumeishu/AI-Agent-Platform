import './assets/main.css'
import './assets/styles.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import loadingDirective from './directives/loading'

const app = createApp(App)

app.use(createPinia())
app.use(router)

// 全局自定义指令
app.directive('loading', loadingDirective)

app.mount('#app')
