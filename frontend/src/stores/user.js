// src/stores/user.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useUserStore = defineStore('user', () => {
    // access token：短时效，只放内存（不持久化，刷新后经 /api/refresh 重新换取）
    const accessToken = ref('')
    // 非敏感信息，可持久化用于展示/路由判断
    const username = ref(localStorage.getItem('username') || '')
    const role = ref(localStorage.getItem('role') || '')
    // 回答风格偏好
    const answerStyle = ref(localStorage.getItem('answer_style') || 'default')

    // 计算属性：判断是否已登录（有 access 或本地用户名；会话有效性由后端 401 兜底）
    const isLoggedIn = computed(() => !!(accessToken.value || username.value))

    /**
     * 清除用户信息（登出：与后端 /api/logout 一起调用以吊销 refresh）
     */
    const logout = () => {
        accessToken.value = ''
        username.value = ''
        role.value = ''
    }

    return {
        accessToken,
        username,
        role,
        answerStyle,
        isLoggedIn,
        logout
    }
}, {
    persist: {
        key: 'user',
        storage: localStorage,
        paths: ['username', 'role', 'answerStyle']
    }
})