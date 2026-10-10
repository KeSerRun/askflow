// src/stores/theme.js
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export const useThemeStore = defineStore('theme', () => {
    // 初始值由 persist 插件从 localStorage 恢复，这里仅作为兜底
    const mode = ref('light')

    const isDark = computed(() => mode.value === 'dark')

    const toggle = () => {
        mode.value = mode.value === 'dark' ? 'light' : 'dark'
    }

    const set = (m) => {
        if (m === 'light' || m === 'dark') {
            mode.value = m
        }
    }

    // 将 <html> 的 data-theme 属性与 mode 同步
    function applyTheme(val) {
        document.documentElement.setAttribute('data-theme', val)
    }

    // 监听 mode 变化自动同步到 DOM
    watch(mode, (val) => {
        applyTheme(val)
    }, { immediate: true })

    return { mode, isDark, toggle, set }
}, {
    persist: {
        key: 'theme-store',
        storage: localStorage,
    },
})
