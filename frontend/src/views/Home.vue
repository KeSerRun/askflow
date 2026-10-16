<template>
  <div class="chat-container" @dragover.prevent @drop.prevent="handlePageDrop">
    <SessionSidebar
      :sessions="sessionList"
      :current-session-id="currentSessionId"
      :is-loading="isLoadingHistory"
      :drawer-open="drawerOpen"
      @create="createNewSession"
      @switch="switchSession"
      @delete="confirmDeleteSession"
      @close="drawerOpen = false"
    />

    <main class="chat-main">
      <ChatHeader
        :title="currentSessionTitle"
        :document-count="documentList.length"
        @open-doc-manager="openDocManager"
        @logout="handleLogout"
        @toggle-sidebar="drawerOpen = !drawerOpen"
      />

      <!-- 规划期任务清单（置顶；set_todolist / check_todo 实时同步） -->
      <div v-if="todolistItems.length" class="todo-panel" :class="{ 'all-done': todoAllDone }">
        <div class="todo-header" @click="todoCollapsed = !todoCollapsed" title="点击折叠 / 展开">
          <span class="todo-title">
            <span class="todo-emoji">{{ todoAllDone ? '✅' : '📋' }}</span>
            <span>{{ todoAllDone ? '全部完成' : '任务清单' }}</span>
          </span>
          <span class="todo-progress" :class="{ done: todoAllDone }">{{ todoDoneCount }}/{{ todolistItems.length }}</span>
          <span class="todo-chevron" :class="{ collapsed: todoCollapsed }">▾</span>
        </div>
        <div class="todo-bar">
          <div class="todo-bar-fill" :style="{ width: todoPercent + '%' }"></div>
        </div>
        <div v-show="!todoCollapsed" class="todo-list">
          <div
            v-for="(it, i) in todolistItems" :key="it.id || i"
            class="todo-item" :class="{ done: it.done }"
            :style="{ '--i': i }"
          >
            <span class="todo-box">{{ it.done ? '✓' : '' }}</span>
            <span class="todo-text">{{ it.text }}</span>
          </div>
        </div>
      </div>

      <MessageList
        ref="messageListRef"
        :messages="messages"
        :is-loading="isLoading"
        :current-session-id="currentSessionId"
        :status-text="agentStatus.visible ? agentStatus.text : ''"
        @download-deliverable="downloadDeliverable"
        @suggest="onSuggest"
      />

      <!-- 选择栏 -->
      <div class="toolbar-row">
        <n-select
          v-model:value="userStore.answerStyle"
          :options="styleOptions"
          :loading="styleLoading"
          size="small"
          style="width: 130px"
          placeholder="风格"
        />
        <n-select
          v-model:value="selectedWorkflow"
          :options="workflowOptions"
          size="small"
          style="width: 130px"
          placeholder="工作流"
        />

        <!-- 上下文使用情况（最小化：仅一行百分比，详请在 tooltip） -->
        <span
          v-if="contextUsage"
          class="context-usage"
          :title="`上下文 ${fmtNum(contextUsage.used)} / ${fmtNum(contextUsage.window)} token`"
        >上下文 {{ contextUsage.pct }}%</span>
      </div>

      <ChatInput
        ref="chatInputRef"
        :is-loading="isLoading"
        :is-uploading="isUploading"
        @send="sendQuestion"
        @stop="stopGeneration"
        @upload="handleFileUpload"
      />

      <!-- 上传进度条 -->
      <div v-if="uploadStatus.visible" class="upload-status-bar">
        <div class="upload-dot"></div>
        <span class="upload-label">{{ uploadStatus.text }}</span>
        <span v-if="uploadStatus.file" class="upload-file" :title="uploadStatus.file">{{ truncateFilename(uploadStatus.file) }}</span>
      </div>
    </main>

    <DocManagerModal
      :is-open="isDocModalOpen"
      :documents="documentList"
      :storage="documentUsage"
      :is-deleting="isDeleting"
      :parse-status="parseStatus"
      :session-id="currentSessionId"
      @close="closeDocManager"
      @delete="confirmDeleteDocs"
      @open="openDocument"
      @refresh="fetchDocuments"
    />

    <!-- 澄清选择框：模型 ask_user_for_clarification（含自定义） -->
    <n-modal
      v-model:show="clarifVisible"
      preset="card"
      style="width: min(520px, calc(100vw - 32px))"
      :mask-closable="!clarifSubmitting"
    >
      <template #header>
        <div class="clarif-head">
          <div class="clarif-title">需要确认</div>
          <div class="clarif-sub">助手在等你确认后继续</div>
        </div>
      </template>

      <div class="clarif-question">{{ clarification?.question }}</div>

      <n-radio-group
        v-if="clarification?.options?.length"
        v-model:value="clarifChoice"
        :disabled="clarifSubmitting"
        class="clarif-options"
      >
        <n-space vertical :size="8">
          <n-radio v-for="(o, i) in clarification.options" :key="i" :value="String(o)">{{ o }}</n-radio>
          <n-radio value="__custom__">自定义…</n-radio>
        </n-space>
      </n-radio-group>

      <n-input
        v-model:value="clarifCustom"
        type="textarea"
        :rows="2"
        placeholder="输入你的回答…"
        class="clarif-input"
        :disabled="clarifSubmitting"
        @keydown.enter.prevent="clarifChoice === '__custom__' && submitClarification()"
      />

      <template #footer>
        <n-space justify="end">
          <n-button :loading="clarifSubmitting" type="primary" :disabled="!clarifValueReady" @click="submitClarification">
            提交并继续
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog, useLoadingBar } from 'naive-ui'

import { useUserStore } from '@/stores/user'
import { useChatStore } from '@/stores/chat'
import { generateNewId } from '@/utils/uuid'
import axios from '@/http/interceptor'

import SessionSidebar from '@/components/SessionSidebar.vue'
import ChatHeader from '@/components/ChatHeader.vue'
import MessageList from '@/components/MessageList.vue'
import ChatInput from '@/components/ChatInput.vue'
import DocManagerModal from '@/components/DocManagerModal.vue'

// Naive UI 组件
import { NSelect, NModal, NInput, NButton, NSpace, NRadio, NRadioGroup, NText } from 'naive-ui'

const router = useRouter()
const userStore = useUserStore()
const message = useMessage()
const dialog = useDialog()
const loadingBar = useLoadingBar()

// --- 状态 ---
const chat = useChatStore()
const isUploading = ref(false)
const isLoadingHistory = ref(false)
const messageListRef = ref(null)
const sessionList = ref([])
const currentSessionId = ref(localStorage.getItem('chat_session_id') || '')

// 当前会话的聊天状态（存于 chat store：切会话 / 进后台都不丢失）
const active = computed(() => chat.sessions[currentSessionId.value] || null)
const messages = computed(() => active.value?.messages || [])
const isLoading = computed(() => !!active.value?.isLoading)
const contextUsage = computed(() => active.value?.contextUsage || null)
const agentStatus = computed(() => active.value?.agentStatus || { visible: false, text: '' })
const todolistItems = computed(() => active.value?.todolistItems || [])
// 任务清单面板（进度 / 折叠 / 完成态）
const todoCollapsed = ref(false)
const todoDoneCount = computed(() => todolistItems.value.filter((it) => it.done).length)
const todoAllDone = computed(
  () => todolistItems.value.length > 0 && todoDoneCount.value === todolistItems.value.length
)
const todoPercent = computed(() =>
  todolistItems.value.length
    ? Math.round((todoDoneCount.value / todolistItems.value.length) * 100)
    : 0
)
// 全部完成时自动展开（“弹出”），即便之前被手动折叠
watch(todoAllDone, (done) => { if (done) todoCollapsed.value = false })
const clarification = computed(() => active.value?.clarification || null)
const clarifVisible = computed({
  get: () => !!active.value?.clarifVisible,
  set: (v) => { if (active.value) active.value.clarifVisible = v },
})
const clarifChoice = computed({
  get: () => active.value?.clarifChoice || '',
  set: (v) => { if (active.value) active.value.clarifChoice = v },
})
const clarifCustom = computed({
  get: () => active.value?.clarifCustom || '',
  set: (v) => { if (active.value) active.value.clarifCustom = v },
})
const clarifSubmitting = computed(() => !!active.value?.clarifSubmitting)
const documentList = computed(() => active.value?.documents || [])
const documentUsage = computed(() => active.value?.usage || { current_mb: 0, max_mb: 0, limit_enabled: false })
const parseStatus = computed(() => active.value?.parseStatus || {})

// MinerU 支持的格式 + 常规文本（txt/md 仅暂存，不解析）+ Office 文档
const ALLOWED_EXTENSIONS = [
  'pdf', 'txt', 'md',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'gif', 'ico',
  'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
]
const MAX_FILE_SIZE = 20 * 1024 * 1024  // 与后端「会话附件总大小上限」保持一致

const isDocModalOpen = ref(false)
const isDeleting = ref(false)
const drawerOpen = ref(false)

// 格式化会话标题：首条消息摘要 + 相对时间
const formatSessionTitle = (firstMsg, createdAt) => {
  const msg = firstMsg ? (firstMsg.length > 20 ? firstMsg.slice(0, 20) + '...' : firstMsg) : ''
  const time = createdAt ? relativeTime(createdAt) : ''
  if (msg && time) return `${msg} · ${time}`
  if (msg) return msg
  return time ? `新会话 · ${time}` : '新会话'
}

const relativeTime = (isoStr) => {
  const now = Date.now()
  const then = new Date(isoStr).getTime()
  const diff = Math.floor((now - then) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 172800) return '昨天'
  return `${Math.floor(diff / 86400)}天前`
}

const currentSessionTitle = computed(() => {
  const session = sessionList.value.find((s) => s.id === currentSessionId.value)
  return session ? session.title || '新会话' : '新会话'
})

// --- 文档管理 ---
const fetchDocuments = () => chat.fetchDocuments(currentSessionId.value)

// ── 附件 MinerU 解析状态（对话页上传 → 解析为 txt，不入向量库） ──
let parseTimer = null
const statusCounts = computed(() => {
  const c = { pending: 0, parsing: 0, success: 0, failed: 0, skipped: 0 }
  for (const s of Object.values(parseStatus.value)) {
    if (c[s.status] != null) c[s.status] += 1
  }
  return c
})

const fetchParseStatus = async () => {
  if (!currentSessionId.value) return
  await chat.fetchParseStatus(currentSessionId.value)
  const busy = statusCounts.value.parsing + statusCounts.value.pending
  if (busy > 0) {
    startParsePolling()
  } else {
    stopParsePolling()
  }
}

function startParsePolling() {
  if (parseTimer) return
  parseTimer = setInterval(fetchParseStatus, 2000)
}
function stopParsePolling() {
  if (parseTimer) { clearInterval(parseTimer); parseTimer = null }
}

const openDocManager = () => {
  isDocModalOpen.value = true
  fetchDocuments()
}

const closeDocManager = () => {
  isDocModalOpen.value = false
}

// 双击文档: 直接下载（blob + <a download>），no 再依赖新标签预览/弹窗
// 附件名可能带 query_img/ 前缀：按段编码，保留路径分隔符
const encDocPath = (name) => String(name).split('/').map(encodeURIComponent).join('/')

// 下载交付物（PDF）：带鉴权请求取 blob 再落盘
const downloadDeliverable = async (msg) => {
  if (!msg || !msg.id) return
  try {
    const resp = await axios.get(`/api/deliverables/${encodeURIComponent(msg.id)}`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${msg.title || '交付物'}.pdf`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    message.error('下载交付物失败')
  }
}

const openDocument = async (docName) => {
  try {
    const response = await axios.get(
      `/api/session_files/file/${encDocPath(docName)}`,
      {
        responseType: 'blob',
        headers: { 'X-Session-ID': currentSessionId.value },
      }
    )
    const url = URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = url
    a.download = String(docName).split('/').pop()
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    // 留一点时间让下载开始后再释放
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    const detail = error.response?.status === 404 ? '原文件已不存在' : '下载失败'
    message.error(detail)
  }
}

const confirmDeleteDocs = (docsToDelete) => {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除选中的 ${docsToDelete.length} 个文档吗？该操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteSelectedDocs(docsToDelete),
  })
}

const deleteSelectedDocs = async (docsToDelete) => {
  isDeleting.value = true
  try {
    await Promise.all(
      docsToDelete.map((name) =>
        axios.delete(`/api/session_files/${encDocPath(name)}`, {
          headers: { 'X-Session-ID': currentSessionId.value },
        })
      )
    )
    chat.pushEvent(currentSessionId.value, 'delete', docsToDelete)
    message.success('附件删除成功')
    await fetchDocuments()
  } catch (error) {
    const detail = error.response?.data?.detail || '删除失败'
    message.error(detail)
  } finally {
    isDeleting.value = false
  }
}

// --- 文件验证 ---
const validateFile = (file) => {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return { valid: false, msg: `不支持的文件类型：${file.name}` }
  }
  if (file.size > MAX_FILE_SIZE) {
    return { valid: false, msg: `${file.name} 大小超过 20MB（会话上限）` }
  }
  return { valid: true }
}

// --- 会话管理 ---
const fetchUserSessions = async () => {
  isLoadingHistory.value = true
  try {
    if (!userStore.username) {
      console.error('未找到用户名')
      return
    }
    const response = await axios.get(`/api/sessions/${userStore.username}`)
    if (response.status === 200) {
      const backendSessions = response.data.sessions || []
      if (backendSessions.length > 0) {
        sessionList.value = backendSessions.map((s) => ({
          id: s.id,
          title: formatSessionTitle(s.first_msg, s.created_at),
        }))
        const latestId = sessionList.value[sessionList.value.length - 1].id
        if (
          !currentSessionId.value ||
          !sessionList.value.find((s) => s.id === currentSessionId.value)
        ) {
          switchSession(latestId)
        } else {
          // 恢复上次会话（如从管理后台返回）：确保 store 有状态并加载历史
          const st = chat.ensure(currentSessionId.value)
          if (!st.historyLoaded && !st.isLoading) chat.loadHistory(currentSessionId.value)
          fetchDocuments()
          fetchParseStatus()
        }
      } else {
        createNewSession()
      }
    }
  } catch (error) {
    console.error('获取会话列表失败:', error)
  } finally {
    isLoadingHistory.value = false
  }
}

const createNewSession = async () => {
  const newId = generateNewId()
  try {
    await axios.post(
      '/api/create_session',
      { session_id: newId },
      { headers: { 'Content-Type': 'application/json' } }
    )
  } catch (error) {
    console.error('创建会话失败:', error)
  }
  sessionList.value.unshift({ id: newId, title: '新会话' })
  switchSession(newId)
}

const confirmDeleteSession = (id) => {
  // SessionSidebar 已经用 Popconfirm 做了二次确认,这里直接执行
  deleteSession(id)
}

const deleteSession = async (id) => {
  try {
    const response = await axios.delete(`/api/sessions/${id}`)
    if (response.status === 200) {
      sessionList.value = sessionList.value.filter((s) => s.id !== id)
      chat.drop(id)
      if (currentSessionId.value === id) {
        if (sessionList.value.length > 0) {
          switchSession(sessionList.value[0].id)
        } else {
          await createNewSession()
        }
      }
      message.success('会话已删除')
    }
  } catch (error) {
    message.error('删除会话失败')
  }
}

const switchSession = async (id) => {
  if (id === currentSessionId.value) return
  const st = chat.ensure(id)
  currentSessionId.value = id
  // 仅在首次进入时加载历史；之后复用 store 中的会话状态。
  // 否则每次切回都会用服务端历史覆盖本地 messages —— 而服务端历史不含"思考过程"（reasoning），
  // 会把已累积的思考记录冲掉。
  if (!st.historyLoaded && !st.isLoading) await chat.loadHistory(id)
  fetchDocuments()
  fetchParseStatus()
}

// --- 提问与流式 ---
let scrollTimer = null
const throttleScroll = () => {
  if (scrollTimer) return
  scrollTimer = requestAnimationFrame(() => {
    messageListRef.value?.scrollToBottom()
    scrollTimer = null
  })
}

// 聊天 / 流式状态已移入 chat store（支持跨会话、跨路由的后台生成）。
// 视图侧仅保留滚动副作用：切换会话或当前会话内容变化时滚动到底部。
watch(
  () => [currentSessionId.value, active.value?.rev],
  () => throttleScroll(),
)

// 记住当前会话：从管理后台等页面返回时恢复同一会话
watch(currentSessionId, (v) => { if (v) localStorage.setItem('chat_session_id', v) })

// 澄清选择框是否已可提交
const clarifValueReady = computed(() => {
  const q = clarification.value
  if (!q) return false
  const opts = q.options || []
  if (opts.length) {
    if (clarifChoice.value === '__custom__') return clarifCustom.value.trim().length > 0
    return clarifChoice.value.length > 0
  }
  return clarifCustom.value.trim().length > 0
})

async function submitClarification() {
  const q = clarification.value
  if (!q || clarifSubmitting.value) return
  let answer = ''
  if ((q.options || []).length) {
    answer = clarifChoice.value === '__custom__' ? clarifCustom.value.trim() : clarifChoice.value
  } else {
    answer = clarifCustom.value.trim()
  }
  if (!answer) { message.warning('请选择或输入你的回答'); return }
  // 续跑在 store 中进行（可后台），无需 await
  chat.resume(currentSessionId.value, answer)
}

const fmtNum = (n) => (Number(n) || 0).toLocaleString('en-US')

// ── 图搜文（已并入 search_knowledge_base 通道，粘贴图片随发送上传） ──

async function uploadPastedImages(images) {
  const keys = []
  for (const img of images || []) {
    try {
      const form = new FormData()
      form.append('file', img.file, (img.file.name || 'pasted.png'))
      const resp = await axios.post(`/api/query/upload_image?session_id=${encodeURIComponent(currentSessionId.value || '')}`, form)
      if (resp.data?.key) keys.push(resp.data.key)
    } catch (err) {
      message.error(`图片上传失败：${err.message}`)
    }
  }
  return keys
}

// 回答风格
const styleOptions = ref([])
const styleLoading = ref(true)

// 工作流
const workflowList = ref([])
const selectedWorkflow = ref('__auto__')
const workflowOptions = computed(() => {
  const opts = [{ label: '自动', value: '__auto__' }]
  for (const wf of workflowList.value) {
    opts.push({ label: wf.label || wf.name, value: wf.name })
  }
  return opts
})

const sendQuestion = async (payload) => {
  const text = (payload && payload.text || '').trim()
  const images = payload && payload.images || []
  // 必须有消息正文（纯图片不支持，需附上文字说明）
  if (!text || isLoading.value) return

  // 确保会话已创建（上传图片需要挂在当前会话目录 sessions/{user_id}/{session_id}/ 下）
  if (!currentSessionId.value) await createNewSession()

  // 附带剪贴板图片：先上传换取对象键（图文检索）
  const imageKeys = images.length ? await uploadPastedImages(images) : []

  // 在 store 中发起：可后台运行，切走 / 进后台都不中断
  chat.send(currentSessionId.value, {
    text,
    imageKeys,
    style: userStore.answerStyle,
    workflow: selectedWorkflow.value === '__auto__' ? null : selectedWorkflow.value,
  })
}

const stopGeneration = () => chat.stop(currentSessionId.value)

// 空对话推荐问题：点击后直接作为消息发送
const onSuggest = (text) => sendQuestion({ text })

// --- 文件上传 ---
const uploadStatus = ref({ visible: false, text: '', file: '' })

// 整页拖拽上传：图片→粘贴链路（图文检索），其余→MinerU（会话附件）
const chatInputRef = ref(null)

const entryToFile = (entry) =>
  new Promise((res) => { entry.file(res, () => res(null)) })

async function walkEntry(entry, out) {
  if (entry.isFile) {
    const f = await entryToFile(entry)
    if (f) out.push(f)
    return
  }
  if (entry.isDirectory) {
    const reader = entry.createReader()
    let all = []
    while (true) {
      const batch = await new Promise((res) => reader.readEntries(res, () => res([])))
      if (!batch.length) break
      all = all.concat(batch)
    }
    for (const child of all) await walkEntry(child, out)
  }
}

async function collectDroppedFiles(dataTransfer) {
  const out = []
  const items = Array.from(dataTransfer.items || [])
  for (const it of items) {
    const entry = typeof it.webkitGetAsEntry === 'function' && it.webkitGetAsEntry()
    if (entry) {
      await walkEntry(entry, out)
    } else if (typeof it.getAsFile === 'function') {
      const f = it.getAsFile()
      if (f) out.push(f)
    }
  }
  return out
}

async function handlePageDrop(e) {
  if (!e.dataTransfer) return
  const files = await collectDroppedFiles(e.dataTransfer)
  if (!files.length) return
  // 交给 ChatInput 统一路由：图片→预览（发送时图文检索），其余→MinerU 上传
  chatInputRef.value?.addFiles(files)
}

const truncateFilename = (name) => {
  if (!name || name.length <= 40) return name
  const ext = name.lastIndexOf('.')
  if (ext > 0) {
    const stem = name.slice(0, 20) + '…' + name.slice(ext)
    return stem
  }
  return name.slice(0, 40) + '…'
}

const handleFileUpload = async (file) => {
  if (!file) return

  const v = validateFile(file)
  if (!v.valid) {
    message.error(v.msg)
    return
  }

  const sessionId = currentSessionId.value
  if (!sessionId) {
    message.error('会话 ID 缺失，请重新登录')
    return
  }

  isUploading.value = true
  uploadStatus.value = { visible: true, text: '上传中…', file: file.name }
  loadingBar.start()

  try {
    const formData = new FormData()
    formData.append('files', file)

    // 会话附件暂存：只落盘到当前会话目录，不解析/不入向量库
    await axios.post('/api/session_files/upload', formData, {
      headers: { 'X-Session-ID': sessionId },
    })
    await fetchDocuments()
    await fetchParseStatus()
    chat.pushEvent(sessionId, 'upload', [file.name])
    message.success(`${file.name} 已暂存到当前会话，正在解析…`)
    loadingBar.finish()
  } catch (error) {
    loadingBar.error()
    const detail = error.response?.data?.detail || '上传失败'
    message.error(detail)
  } finally {
    isUploading.value = false
    uploadStatus.value = { visible: false, text: '', file: '' }
  }
}

const handleLogout = () => {
  dialog.warning({
    title: '退出登录',
    content: '确定要退出当前账号吗？',
    positiveText: '退出',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await axios.post('/api/logout')  // 清 httpOnly cookie
      } catch (e) { /* 忽略：本地仍然登出 */ }
      userStore.logout()
      router.push('/login')
    },
  })
}

onMounted(() => {
  fetchUserSessions()
  fetchDocuments()
  // 加载风格
  axios.get('/api/styles').then(r => {
    if (r.status === 200 && r.data.styles) {
      styleOptions.value = r.data.styles.map(s => ({
        value: s.value,
        label: s.label || s.value,
        description: s.description || '',
      }))
    }
  }).catch(() => {
    styleOptions.value = [{ label: '默认', value: 'default' }]
  }).finally(() => { styleLoading.value = false })
  // 加载工作流列表
  axios.get('/api/workflows').then(r => {
    workflowList.value = r.data.workflows || []
  }).catch(e => console.warn('获取工作流列表失败', e))
})

onUnmounted(() => {
  if (scrollTimer) cancelAnimationFrame(scrollTimer)
  scrollTimer = null
  stopParsePolling()
})
</script>

<style scoped>
.chat-container {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
  /* 对话页背景：极淡暖色柔光，避免大面积平色；白底的气泡/顶栏/输入条因此更立体 */
  background:
    radial-gradient(1000px 560px at 6% -10%, var(--color-primary-bg-active), transparent 60%),
    radial-gradient(820px 480px at 108% 108%, var(--color-primary-bg-subtle), transparent 58%),
    var(--color-bg-body);
}

.chat-main {
  flex: 1;

  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 工作流/风格选择工具栏 */
.toolbar-row {
  display: flex;
  gap: 8px;
  padding: 6px 24px 0;
  max-width: 880px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
  flex-shrink: 0;
}

.toolbar-row .n-select .n-base-selection-input,
.toolbar-row .n-select .n-base-selection-overlay {
  padding-top: 5px;
}

.upload-status-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid var(--color-border);
  background-color: var(--color-bg-card);
  animation: fadeIn 0.2s ease-out;
}

.upload-status-bar .upload-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--color-primary);
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.upload-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--color-primary);
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.upload-label {
  font-size: 13px;
  color: var(--color-text-3);
  flex-shrink: 0;
}

.upload-file {
  font-size: 12px;
  color: var(--color-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
  direction: rtl;
  text-align: left;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 上下文使用情况指示器（最小化） */
.context-usage {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-3);
  white-space: nowrap;
  cursor: default;
}

/* 规划期任务清单 */
.todo-panel {
  margin: 12px auto 0;
  max-width: 880px;
  width: calc(100% - 48px);
  padding: 10px 14px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 14px;
  background: var(--color-bg-card);
  box-shadow: 0 2px 10px var(--color-shadow-card);
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
  animation: todoIn 0.25s ease-out;
}
.todo-panel.all-done {
  border-color: var(--color-success);
  box-shadow: 0 2px 14px rgba(24, 160, 88, 0.18);
}
.todo-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.todo-title {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-1);
}
.todo-emoji { font-size: 14px; }
.todo-progress {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-neutral-wash);
  color: var(--color-text-3);
  transition: background-color 0.25s ease, color 0.25s ease;
}
.todo-progress.done {
  background: rgba(24, 160, 88, 0.15);
  color: var(--color-success);
}
.todo-chevron {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--color-text-3);
  transition: transform 0.2s ease;
}
.todo-chevron.collapsed { transform: rotate(-90deg); }
.todo-bar {
  height: 4px;
  margin: 8px 0 2px;
  border-radius: 999px;
  background: var(--color-neutral-wash);
  overflow: hidden;
}
.todo-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--color-primary);
  transition: width 0.3s ease, background-color 0.3s ease;
}
.todo-panel.all-done .todo-bar-fill { background: var(--color-success); }
.todo-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 6px;
}
.todo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 6px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text-1);
  transition: background-color 0.15s ease;
  transition-delay: calc(var(--i, 0) * 90ms);
}
.todo-item:hover { background: var(--color-neutral-wash-light); }
.todo-box {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1.5px solid var(--color-border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  line-height: 1;
  color: #fff;
  transition: background-color 0.2s ease, border-color 0.2s ease;
  transition-delay: calc(var(--i, 0) * 90ms);
}
.todo-item.done .todo-box {
  background: var(--color-success);
  border-color: var(--color-success);
}
.todo-text {
  flex: 1;
  transition: color 0.2s ease;
  transition-delay: calc(var(--i, 0) * 90ms);
}
.todo-item.done .todo-text {
  color: var(--color-text-3);
  text-decoration: line-through;
  text-decoration-color: var(--color-border);
}
@keyframes todoIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

/* 澄清选择框 */
/* 澄清确认弹窗 */
.clarif-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.clarif-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-1);
}

.clarif-sub {
  font-size: 12px;
  color: var(--color-text-3);
}

.clarif-question {
  margin-bottom: 14px;
  padding: 12px 14px;
  border-left: 3px solid var(--color-primary);
  border-radius: 10px;
  background: var(--color-primary-bg-subtle);
  font-size: 14px;
  line-height: 1.65;
  color: var(--color-text-1);
  white-space: pre-wrap;
}

/* 选项做成可点卡片：比裸 radio 更好点、更好看 */
.clarif-options :deep(.n-radio) {
  display: flex;
  align-items: flex-start;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.clarif-options :deep(.n-radio:hover) {
  border-color: var(--color-primary);
  background: var(--color-primary-bg-subtle);
}

.clarif-options :deep(.n-radio--checked) {
  border-color: var(--color-primary);
  background: var(--color-primary-bg-subtle);
}

.clarif-options :deep(.n-radio__label) {
  white-space: normal;
  line-height: 1.6;
}

.clarif-input {
  margin-top: 12px;
}
</style>
