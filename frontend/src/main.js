import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

// Naive UI 推荐字体(可选,但能让排版更稳)
import 'vfonts/Lato.css'
import 'vfonts/FiraCode.css'

// 代码高亮样式
import 'highlight.js/styles/github-dark.css'

// LaTeX 数学公式样式
import 'katex/dist/katex.min.css'

// 全局颜色变量
import '@/assets/variables.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)
app.use(router)

app.mount('#app')
