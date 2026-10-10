// src/stores/admin.js
// 管理后台 API 封装
import { ref } from 'vue'
import { defineStore } from 'pinia'
import axios from '@/http/interceptor'

export const useAdminStore = defineStore('admin', () => {
  const loading = ref(false)
  const error = ref(null)

  async function apiCall(fn) {
    loading.value = true
    error.value = null
    try {
      return await fn()
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // --- 仪表盘 ---
  const dashboardData = ref(null)

  async function fetchDashboard() {
    const res = await apiCall(() => axios.get('/api/admin/dashboard'))
    dashboardData.value = res.data
    return res.data
  }

  // --- 健康检查 ---
  const healthData = ref(null)
  const healthLoading = ref(false)

  async function fetchHealth() {
    healthLoading.value = true
    try {
      const res = await axios.get('/api/health/check')
      healthData.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      healthLoading.value = false
    }
  }

  // --- 配置 ---
  const configData = ref(null)

  async function fetchConfig() {
    const res = await apiCall(() => axios.get('/api/admin/config'))
    configData.value = res.data
    return res.data
  }

  const configSchema = ref([])

  async function fetchConfigSchema() {
    try {
      const res = await axios.get('/api/admin/config/schema')
      configSchema.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
    }
  }

  async function updateConfig(updates) {
    const res = await apiCall(() => axios.put('/api/admin/config', updates))
    await fetchConfig()
    return res.data
  }

  // --- 用户管理 ---
  const usersData = ref({ total: 0, items: [] })

  async function fetchUsers(page = 1, pageSize = 20) {
    const res = await apiCall(() => axios.get('/api/admin/users', { params: { page, page_size: pageSize } }))
    usersData.value = res.data
    return res.data
  }

  async function createUser(username, password, role = 'user') {
    const res = await apiCall(() => axios.post('/api/admin/users', { username, password, role }))
    await fetchUsers()
    return res.data
  }

  async function deleteUser(username) {
    const res = await apiCall(() => axios.delete(`/api/admin/users/${encodeURIComponent(username)}`))
    await fetchUsers()
    return res.data
  }

  async function changeUserRole(username, role) {
    const res = await apiCall(() => axios.put(`/api/admin/users/${encodeURIComponent(username)}/role`, { role }))
    await fetchUsers()
    return res.data
  }

  async function resetUserPassword(username, password) {
    return apiCall(() =>
      axios.put(`/api/admin/users/${encodeURIComponent(username)}/password`, { password })
    )
  }

  return {
    loading, error,
    dashboardData, fetchDashboard,
    healthData, healthLoading, fetchHealth,
    configData, configSchema, fetchConfig, fetchConfigSchema, updateConfig,
    usersData, fetchUsers, createUser, deleteUser, changeUserRole, resetUserPassword,
  }
})
