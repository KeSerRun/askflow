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

  async function fetchServerResources() {
    const res = await apiCall(() => axios.get('/api/admin/dashboard/resources'))
    serverResources.value = res.data
    return res.data
  }

  async function resetRequestStats() {
    const res = await apiCall(() => axios.post('/api/admin/dashboard/reset_request_stats'))
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

  async function restartBackend() {
    const res = await apiCall(() => axios.post('/api/admin/restart'))
    return res.data
  }

  // --- 交付物模板 ---
  const deliverableTemplates = ref([])

  async function fetchDeliverableTemplates() {
    const res = await apiCall(() => axios.get('/api/admin/deliverables/templates'))
    deliverableTemplates.value = res.data?.templates || []
    return deliverableTemplates.value
  }

  async function fetchDeliverableTemplate(name) {
    const res = await apiCall(() =>
      axios.get(`/api/admin/deliverables/templates/${encodeURIComponent(name)}`))
    return res.data
  }

  async function saveDeliverableTemplate(name, payload) {
    const res = await apiCall(() =>
      axios.put(`/api/admin/deliverables/templates/${encodeURIComponent(name)}`, payload))
    await fetchDeliverableTemplates()
    return res.data
  }

  async function deleteDeliverableTemplate(name) {
    const res = await apiCall(() =>
      axios.delete(`/api/admin/deliverables/templates/${encodeURIComponent(name)}`))
    await fetchDeliverableTemplates()
    return res.data
  }

  async function previewDeliverableTemplate(name) {
    // 返回 PDF blob（调用方自行 objectURL 打开）
    const res = await axios.post(
      `/api/admin/deliverables/templates/${encodeURIComponent(name)}/preview`,
      null, { responseType: 'blob' },
    )
    return res.data
  }

  async function resetDeliverableTemplates() {
    const res = await apiCall(() => axios.post('/api/admin/deliverables/templates/reset'))
    await fetchDeliverableTemplates()
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

  // --- 数据管理（向量库 / 文档） ---
  const dbStats = ref(null)
  const dbChunks = ref({ total: 0, items: [] })
  const systemDocs = ref([])
  const systemDocsTotal = ref(0)
  // 服务器资源（仪表盘 CPU / RAM）
  const serverResources = ref(null)

  async function fetchDbStats() {
    const res = await apiCall(() => axios.get('/api/admin/database'))
    dbStats.value = res.data
    return res.data
  }

  // --- 知识库管理 ---
  const knowledgeBases = ref([])        // 当前页（知识库管理网格展示）
  const knowledgeBasesTotal = ref(0)
  const allKnowledgeBases = ref([])   // 全量（下拉选择等场景，不受分页/搜索影响）

  /** 拉取知识库列表（支持分页 + 模糊搜索）。 */
  async function fetchKnowledgeBases(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/database/knowledge_bases', { params }))
    const data = res.data || {}
    knowledgeBases.value = data.knowledge_bases || []
    knowledgeBasesTotal.value = data.total ?? knowledgeBases.value.length
    return res.data
  }

  /** 取全部知识库（不分页），供下拉选择等场景使用。 */
  async function fetchAllKnowledgeBases() {
    const res = await apiCall(() => axios.get('/api/admin/database/knowledge_bases', { params: { page_size: 0 } }))
    allKnowledgeBases.value = res.data?.knowledge_bases || []
    return allKnowledgeBases.value
  }

  async function createKnowledgeBase(name, description = '') {
    const res = await apiCall(() => axios.post('/api/admin/database/knowledge_bases', { name, description }))
    await fetchAllKnowledgeBases()
    return res.data
  }

  async function updateKnowledgeBase(name, newName, description) {
    const res = await apiCall(() => axios.put(`/api/admin/database/knowledge_bases/${encodeURIComponent(name)}`, { new_name: newName, description }))
    await fetchAllKnowledgeBases()
    return res.data
  }

  async function deleteKnowledgeBase(name) {
    const res = await apiCall(() => axios.delete(`/api/admin/database/knowledge_bases/${encodeURIComponent(name)}`))
    await fetchAllKnowledgeBases()
    return res.data
  }

  async function fetchDbChunks(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/database/chunks', { params }))
    dbChunks.value = res.data
    return res.data
  }

  async function fetchSystemDocs(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/database/system_docs', { params }))
    systemDocs.value = res.data.documents || []
    systemDocsTotal.value = res.data.total || 0
    return res.data
  }

  /** 只取某知识库的文档名，供「文档视图」下拉用 —— 不污染 systemDocs（那是文档管理的全库列表） */
  async function fetchKbDocOptions(partition) {
    const res = await apiCall(() =>
      axios.get('/api/admin/database/system_docs', { params: { partition, page_size: 200 } })
    )
    return (res.data.documents || []).map(d => ({ label: d.name, value: d.name }))
  }

  const systemFiles = ref([])
  const systemFilesTotal = ref(0)
  async function fetchSystemFiles(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/database/system_files', { params }))
    systemFiles.value = res.data.files || []
    systemFilesTotal.value = res.data.total || 0
    return res.data
  }

  async function fetchDbMdView(source, partition) {
    const res = await apiCall(() => axios.get('/api/admin/database/md_view', { params: { source, partition } }))
    return res.data
  }

  async function mdviewEmbed(payload) {
    const res = await apiCall(() => axios.post('/api/admin/database/mdview/embed', payload))
    return res.data
  }

  async function mdviewRemove(payload) {
    const res = await apiCall(() => axios.post('/api/admin/database/mdview/remove', payload))
    return res.data
  }

  async function fetchChunkParent(parentId) {
    const res = await apiCall(() => axios.get('/api/admin/database/parent', { params: { id: parentId } }))
    return res.data
  }

  async function uploadSystemDocs(files, partition) {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    // partition 是后端的 Query 参数，必须放在 URL 上（放 FormData 后端收不到）
    const res = await apiCall(() => axios.post('/api/admin/database/upload', form, {
      params: { partition },
    }))
    return res.data
  }

  async function fetchUploadTask(taskId) {
    try {
      const res = await axios.get(`/api/admin/database/upload/task/${taskId}`)
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function deleteDocument(source, partition) {
    const res = await apiCall(() =>
      axios.delete('/api/admin/database/delete', { params: { source, partition } })
    )
    await fetchDbStats()
    return res.data
  }

  async function deleteSystemRawFile(source, partition) {
    const res = await apiCall(() =>
      axios.delete('/api/admin/database/system_file', { params: { source, partition } })
    )
    await fetchDbStats()
    return res.data
  }

  // --- Prompt 管理（identity / workflow / style） ---
  const promptsOverview = ref(null)

  async function fetchPrompts() {
    const res = await apiCall(() => axios.get('/api/admin/prompts'))
    promptsOverview.value = res.data
    return res.data
  }

  async function fetchPrompt(type, name) {
    const res = await apiCall(() => axios.get(`/api/admin/prompts/${type}/${encodeURIComponent(name)}`))
    return res.data
  }

  async function savePrompt(type, name, content) {
    const res = await apiCall(() => axios.put(`/api/admin/prompts/${type}/${encodeURIComponent(name)}`, { content }))
    return res.data
  }

  async function deletePrompt(type, name) {
    const res = await apiCall(() => axios.delete(`/api/admin/prompts/${type}/${encodeURIComponent(name)}`))
    return res.data
  }

  async function activateIdentity(name) {
    const res = await apiCall(() => axios.post(`/api/admin/prompts/identity/${encodeURIComponent(name)}/activate`))
    return res.data
  }

  // --- 会话管理（全部用户） ---
  const sessionsData = ref({ total: 0, items: [] })

  async function fetchSessions(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/sessions', { params }))
    sessionsData.value = res.data
    return res.data
  }

  async function fetchSessionHistory(session_id) {
    const res = await apiCall(() =>
      axios.get(`/api/admin/sessions/${encodeURIComponent(session_id)}/history`)
    )
    return res.data.history || []
  }

  async function clearSessionHistory(session_id) {
    const res = await apiCall(() =>
      axios.post(`/api/admin/sessions/${encodeURIComponent(session_id)}/history/clear`)
    )
    return res.data
  }

  async function deleteSessionAdmin(session_id) {
    const res = await apiCall(() =>
      axios.delete(`/api/admin/sessions/${encodeURIComponent(session_id)}`)
    )
    await fetchSessions()
    return res.data
  }

  // --- 日志管理（查数据库表 app_logs / request_logs） ---
  const appLogsData = ref({ total: 0, items: [] })
  const httpLogsData = ref({ total: 0, items: [] })

  async function fetchAppLogs(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/logs/app', { params }))
    appLogsData.value = res.data || { total: 0, items: [] }
    return appLogsData.value
  }

  async function fetchHttpLogs(params = {}) {
    const res = await apiCall(() => axios.get('/api/admin/logs/http', { params }))
    httpLogsData.value = res.data || { total: 0, items: [] }
    return httpLogsData.value
  }

  async function deleteAppLog(id) {
    const res = await apiCall(() => axios.delete(`/api/admin/logs/app/${id}`))
    return res.data
  }

  async function deleteHttpLog(id) {
    const res = await apiCall(() => axios.delete(`/api/admin/logs/http/${id}`))
    return res.data
  }

  async function clearAppLogs() {
    const res = await apiCall(() => axios.delete('/api/admin/logs/app'))
    return res.data
  }

  async function clearHttpLogs() {
    const res = await apiCall(() => axios.delete('/api/admin/logs/http'))
    return res.data
  }

  // --- 工具管理 ---
  const toolsData = ref([])
  const toolsTotal = ref(0)
  async function fetchTools(page = 1, pageSize = 0, keyword = '') {
    const res = await apiCall(() => axios.get('/api/admin/tools', {
      params: { page, page_size: pageSize, keyword: keyword || undefined },
    }))
    toolsData.value = res.data?.items || []
    toolsTotal.value = res.data?.total || 0
    return toolsData.value
  }
  async function createTool(payload) {
    const res = await apiCall(() => axios.post('/api/admin/tools', payload))
    return res.data
  }
  async function updateTool(name, payload) {
    const res = await apiCall(() => axios.put(`/api/admin/tools/${encodeURIComponent(name)}`, payload))
    return res.data
  }
  async function deleteTool(name) {
    const res = await apiCall(() => axios.delete(`/api/admin/tools/${encodeURIComponent(name)}`))
    return res.data
  }

  async function resetBuiltinTools() {
    const res = await apiCall(() => axios.post('/api/admin/tools/reset'))
    return res.data
  }
  async function resetToolCallCounts() {
    const res = await apiCall(() => axios.post('/api/admin/tools/reset_call_counts'))
    return res.data
  }
  async function testTool(name, args) {
    const res = await apiCall(() => axios.post(`/api/admin/tools/${encodeURIComponent(name)}/test`, { args }))
    return res.data
  }

  async function uploadTestImage(file) {
    const form = new FormData()
    form.append('file', file, file.name || 'pasted.png')
    const res = await apiCall(() => axios.post('/api/query/upload_image?session_id=', form))
    return (res.data && res.data.key) || ''
  }

  async function uploadToolSource(name, file) {
    const form = new FormData()
    form.append('file', file)
    const res = await apiCall(() => axios.post(`/api/admin/tools/${encodeURIComponent(name)}/source`, form))
    return res.data
  }

  async function fetchToolSource(name) {
    const res = await apiCall(() => axios.get(`/api/admin/tools/${encodeURIComponent(name)}/source`))
    return res.data
  }

  return {
    loading, error,
    dashboardData, fetchDashboard,
    serverResources, fetchServerResources, resetRequestStats,
    healthData, healthLoading, fetchHealth,
    configData, configSchema, fetchConfig, fetchConfigSchema, updateConfig, restartBackend,
    deliverableTemplates, fetchDeliverableTemplates, fetchDeliverableTemplate,
    saveDeliverableTemplate, deleteDeliverableTemplate, previewDeliverableTemplate,
    resetDeliverableTemplates,
    usersData, fetchUsers, createUser, deleteUser, changeUserRole, resetUserPassword,
    dbStats, dbChunks, systemDocs, systemDocsTotal,
    fetchDbStats, fetchDbChunks, fetchDbMdView, mdviewEmbed, mdviewRemove, fetchChunkParent,
    fetchSystemDocs, fetchKbDocOptions, fetchSystemFiles, systemFiles, systemFilesTotal,
    uploadSystemDocs, fetchUploadTask,
    deleteDocument, deleteSystemRawFile,
    sessionsData, fetchSessions, fetchSessionHistory, clearSessionHistory, deleteSessionAdmin,
    appLogsData, httpLogsData, fetchAppLogs, fetchHttpLogs,
    deleteAppLog, deleteHttpLog, clearAppLogs, clearHttpLogs,
    toolsData, toolsTotal, fetchTools, createTool, updateTool, deleteTool, testTool, resetBuiltinTools, resetToolCallCounts, uploadTestImage,
    uploadToolSource, fetchToolSource,
    promptsOverview, fetchPrompts, fetchPrompt, savePrompt, deletePrompt, activateIdentity,
    knowledgeBases, knowledgeBasesTotal, allKnowledgeBases,
    fetchKnowledgeBases, fetchAllKnowledgeBases,
    createKnowledgeBase, updateKnowledgeBase, deleteKnowledgeBase,
  }
})
