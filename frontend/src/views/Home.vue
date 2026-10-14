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

      <!-- 规划期任务清单（置顶：模型说"见上方清单"时真实可见；set_todolist / check_todo 实时同步） -->
      <div v-if="todolistItems.length" class="todo-panel">
        <div class="todo-header">📋 任务清单</div>
        <div class="todo-list">
          <div
            v-for="(it, i) in todolistItems" :key="it.id || i"
            class="todo-item" :class="{ done: it.done }"
          >
            <span class="todo-box">{{ it.done ? '✓' : '○' }}</span>
            <span class="todo-text">{{ it.text }}</span>
            <span v-if="it.done" class="todo-done-tag">完成</span>
          </div>
        </div>
      </div>

      <MessageList
        ref="messageListRef"
        :messages="messages"
        :is-loading="isLoading"
        :current-session-id="currentSessionId"
        :status-text="agentStatus.visible ? agentStatus.text : ''"
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
          :title="`上下文 ${fmtChars(contextUsage.used)} / ${fmtChars(contextUsage.window)} 字符`"
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
    <n-modal v-model:show="clarifVisible" preset="card" title="❓ 需要确认" style="width: 520px"
      :mask-closable="!clarifSubmitting">
      <div class="clarif-question">{{ clarification?.question }}</div>
      <n-radio-group v-if="clarification?.options?.length" v-model:value="clarifChoice" :disabled="clarifSubmitting">
        <n-space vertical>
          <n-radio v-for="(o, i) in clarification.options" :key="i" :value="String(o)">{{ o }}</n-radio>
          <n-radio value="__custom__">自定义…</n-radio>
        </n-space>
      </n-radio-group>
      <n-input
        v-model:value="clarifCustom"
        type="textarea"
        :rows="2"
        placeholder="输入你的回答…"
        style="margin-top: 10px"
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
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, useDialog, useLoadingBar } from 'naive-ui'

import { useUserStore } from '@/stores/user'
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
const messages = ref([])
let msgKeyCounter = 0

function nextMsgKey() {
  return ++msgKeyCounter
}
const isLoading = ref(false)
const isUploading = ref(false)
const isLoadingHistory = ref(false)
const messageListRef = ref(null)
const sessionList = ref([])
const currentSessionId = ref('')

// MinerU 支持的格式 + 常规文本（txt/md 仅暂存，不解析）+ Office 文档
const ALLOWED_EXTENSIONS = [
  'pdf', 'txt', 'md',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'gif', 'ico',
  'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
]
const MAX_FILE_SIZE = 20 * 1024 * 1024  // 与后端「会话附件总大小上限」保持一致

const documentList = ref([])
const documentUsage = ref({ current_mb: 0, max_mb: 0, limit_enabled: false })
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
const fetchDocuments = async () => {
  if (!currentSessionId.value) {
    documentList.value = []
    documentUsage.value = { current_mb: 0, max_mb: 0, limit_enabled: false }
    parseStatus.value = {}
    return
  }
  try {
    const response = await axios.get('/api/session_files', {
      headers: { 'X-Session-ID': currentSessionId.value },
    })
    if (response.status === 200) {
      documentList.value = (response.data.files || []).map((f) => ({
        name: f.name,
        size: f.size || 0,
        kind: f.kind || 'file',
      }))
      if (response.data.usage) documentUsage.value = response.data.usage
    }
  } catch (error) {
    console.error('获取会话附件失败:', error)
  }
}

// ── 附件 MinerU 解析状态（对话页上传 → 解析为 txt，不入向量库） ──
const parseStatus = ref({})
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
  try {
    const res = await axios.get('/api/session_files/parse_status', {
      headers: { 'X-Session-ID': currentSessionId.value },
    })
    parseStatus.value = res.data?.files || {}
    const busy = statusCounts.value.parsing + statusCounts.value.pending
    if (busy > 0) {
      startParsePolling()
    } else {
      stopParsePolling()
    }
  } catch (error) {
    console.error('获取附件解析状态失败:', error)
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
    const del = new Set(docsToDelete)
    documentList.value = documentList.value.filter((doc) => !del.has(doc.name))
    messages.value.push({ role: 'event', content: eventText('delete', docsToDelete), _key: nextMsgKey() })
    throttleScroll()
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
  currentSessionId.value = id
  messages.value = []
  isLoading.value = true
  try {
    await loadHistoryMessages(id)
  } catch (error) {
    console.error('加载历史失败', error)
  } finally {
    isLoading.value = false
  }
}

// 用户消息清洗：剥离后端注入的"附带图片"说明块，还原为可见文本 + 附带图片标注
function cleanUserMessage(content = '') {
  const text = String(content || '')
  const m = text.match(/\n\n\[用户附带了图片，图片对象键：(.*?)。/)
  if (!m) return { role: 'user', content: text }
  let attach
  try {
    const arr = JSON.parse(m[1])
    attach = Array.isArray(arr) && arr.length ? arr : undefined
  } catch (e) {
    attach = undefined
  }
  return { role: 'user', content: text.slice(0, m.index), _attachments: attach }
}

// 事件条目（上传/删除附件、切换风格）→ 聊天列表中的操作提示文本
function eventText(type, files = []) {
  const names = Array.isArray(files) ? files : []
  const head = names.slice(0, 3).join('、')
  const suffix = names.length > 3 ? ' 等' : ''
  if (type === 'upload') return `已上传附件：${head}${suffix}`
  if (type === 'delete') return `已删除附件：${head}${suffix}`
  if (type === 'delete_all') return '已清空全部附件'
  if (type === 'style_change') return `切换回答风格：${names[0] || 'default'}`
  return ''
}

const loadHistoryMessages = async (sessionId) => {
  try {
    const response = await axios.get(`/api/history/${sessionId}`)
    contextUsage.value = null  // 切会话后重置上下文指示
    if (response.status === 200) {
      const data = response.data
      const newMessages = []
      for (const msg of data.history || []) {
        // 事件条目：渲染为居中小字操作提示（同时后端已注入 LLM 上下文）
        if (msg.type === 'event') {
          const text = eventText(msg.event_type, msg.files)
          if (text) newMessages.push({ role: 'event', content: text, _key: nextMsgKey() })
          continue
        }
        if (msg.type === 'turn') {
          // 完整对话回合：从 messages 数组中提取 user/assistant 消息
          for (const m of msg.messages || []) {
            if (m.role === 'user') {
              newMessages.push({ ...cleanUserMessage(m.content), _key: nextMsgKey() })
            } else if (m.role === 'assistant' && !m.tool_calls) {
              newMessages.push({ role: 'ai', content: m.content || '', _key: nextMsgKey() })
            }
            // tool 消息不渲染，仅供 LLM 上下文使用
          }
          continue
        }
        // 旧格式 qa 对
        if (msg.user == null && msg.assistant == null) continue
        newMessages.push(
          { role: 'user', content: msg.user || '', _key: nextMsgKey() },
          { role: 'ai', content: msg.assistant || '', _key: nextMsgKey() }
        )
      }
      messages.value = newMessages
    } else {
      messages.value = []
    }
  } catch (e) {
    messages.value = []
  }
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

let lastProcessedLength = 0
let sseBuffer = ''

// ── SSE 流式事件处理（发送 / 续答复用）──
let sseCtx = null   // { aiIndex, content, reasoning, version, chunk, reasoningDirty }

function beginSse(aiIndex) {
  sseBuffer = ''
  lastProcessedLength = 0
  sseCtx = { aiIndex, content: '', reasoning: '', version: 0, chunk: '', reasoningDirty: false }
  return sseCtx
}

function flushSse(force = false) {
  const ctx = sseCtx
  if (!ctx) return
  if (ctx.chunk) {
    ctx.content += ctx.chunk
    ctx.chunk = ''
    ctx.version++
  }
  // 正文或有新的思考内容时都刷新（否则纯思考阶段 version 不增长，思考过程不会流式显示）
  if (ctx.version || ctx.reasoningDirty || force) {
    ctx.reasoningDirty = false
    messages.value[ctx.aiIndex] = {
      role: 'ai', content: ctx.content, reasoning: ctx.reasoning, _v: ctx.version,
    }
    throttleScroll()
  }
}

function applySseContent(content) {
  const ctx = sseCtx
  if (!ctx) return
  if (typeof content === 'string') { ctx.chunk += content; return }   // 旧格式纯字符串 token
  if (typeof content !== 'object' || !content) return

  if (content.type === 'status') {
    const label = statusLabels[content.status]
    if (content.status === 'thinking' || content.status === 'calling_tool') {
      agentStatus.value = {
        visible: true,
        text: typeof label === 'function' ? label(content) : (label || '处理中…'),
      }
    } else if (content.status === 'tool_result') {
      const summary = typeof label === 'function' ? label(content) : ''
      agentStatus.value = summary ? { visible: true, text: summary } : { visible: false, text: '' }
    } else if (content.status === 'ask_user') {
      clarification.value = {
        question: content.question || '',
        options: Array.isArray(content.options) ? content.options : [],
      }
      clarifChoice.value = ''
      clarifCustom.value = ''
      clarifVisible.value = true
    } else if (content.status === 'todolist') {
      todolistItems.value = Array.isArray(content.items) ? content.items : []
    } else if (content.status === 'cancelled') {
      const cancelMsg = { role: 'ai', content: '', _key: nextMsgKey(), isCancelled: true }
      messages.value[ctx.aiIndex]
        ? Object.assign(messages.value[ctx.aiIndex], cancelMsg)
        : messages.value.push(cancelMsg)
      agentStatus.value = { visible: false, text: '' }
    }
    return
  }
  if (content.type === 'token') {
    agentStatus.value = { visible: false, text: '' }
    ctx.chunk += content.text || ''
    return
  }
  if (content.type === 'reasoning') {
    ctx.reasoning += content.text || ''
    ctx.reasoningDirty = true
    return   // 交由本次 download 的收尾 flushSse 统一刷新
  }
  if (content.type === 'context') {
    const used = Number(content.used_chars) || 0
    const win = Number(content.window_chars) || 0
    contextUsage.value = { used, window: win, pct: win ? Math.round((used / win) * 100) : 0 }
  }
}

// axios onDownloadProgress 处理器：增量解析 SSE（只处理 \n\n 结束的完整事件）
function sseDownloadHandler() {
  return (progressEvent) => {
    const fullText = progressEvent.event.target.responseText || ''
    const newText = fullText.slice(lastProcessedLength)
    if (!newText) return
    lastProcessedLength = fullText.length
    sseBuffer += newText
    const events = sseBuffer.split('\n\n')
    sseBuffer = events.pop() || ''
    for (const event of events) {
      for (const line of event.split('\n')) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const raw = trimmed.slice(5)
        if (!raw || raw === '[DONE]') continue
        let content
        try { content = JSON.parse(raw) } catch { content = raw }
        if (!content) continue
        applySseContent(content)
      }
    }
    flushSse(false)
  }
}

// 收尾：任务清单收纳进本轮 AI 消息 + 落定最终内容
function finalizeSse() {
  const ctx = sseCtx
  if (ctx && todolistItems.value && todolistItems.value.length) {
    const allDone = todolistItems.value.every(it => it.done)
    const mark = allDone ? '✅' : '📋'
    ctx.content += `\n\n---\n${mark} 任务清单（${allDone ? '全部完成' : '未全部完成'}）\n` +
      todolistItems.value.map(it => `- ${it.done ? '[x]' : '[ ]'} ${it.text}`).join('\n')
    ctx.version++
    todolistItems.value = []
  }
  flushSse(true)
  sseBuffer = ''
  sseCtx = null
}

// Agent 状态追踪
const agentStatus = ref({ visible: false, text: '' })
const todolistItems = ref([])   // 规划期任务清单（set_todolist / check_todo 事件驱动）

// 澄清选择框（ask_user_for_clarification）
const clarification = ref(null)      // { question, options }
const clarifVisible = ref(false)
const clarifChoice = ref('')
const clarifCustom = ref('')
const clarifSubmitting = ref(false)
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

  // 立刻关闭弹窗并上屏用户回答，避免长续跑期间页面像卡死
  clarifVisible.value = false
  clarification.value = null
  messages.value.push({ role: 'user', content: answer, _key: nextMsgKey() })
  messages.value.push({ role: 'ai', content: '', reasoning: '', _v: 0, _key: nextMsgKey() })
  const aiIdx = messages.value.length - 1
  clarifSubmitting.value = true
  agentStatus.value = { visible: true, text: '正在继续生成…' }
  isLoading.value = true
  contextUsage.value = null
  beginSse(aiIdx)
  throttleScroll()

  try {
    // 续跑同样走流式（stream: true），与 /api/query 共用 SSE 处理
    await axios.post(
      '/api/query/resume',
      { session_id: currentSessionId.value, answer, stream: true },
      {
        headers: { 'Content-Type': 'application/json' },
        responseType: 'text',
        onDownloadProgress: sseDownloadHandler(),
      },
    )
  } catch (e) {
    const ctx = sseCtx
    const errMsg = (e && e.response && e.response.data && e.response.data.detail) || (e && e.message) || '未知错误'
    if (ctx) {
      ctx.content += `\n\n*[继续生成失败：${errMsg}]*`
      ctx.version++
      messages.value[ctx.aiIndex] = {
        role: 'ai', content: ctx.content, reasoning: ctx.reasoning, _v: ctx.version,
      }
    }
  } finally {
    agentStatus.value = { visible: false, text: '' }
    isLoading.value = false
    clarifSubmitting.value = false
    finalizeSse()
    nextTick(() => messageListRef.value?.scrollToBottom())
  }
}

// 上下文使用情况（来自后端 context 事件）
const contextUsage = ref(null)
const fmtChars = (n) => (Number(n) || 0).toLocaleString('en-US')

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

const statusLabels = {
  thinking: '深度思考中…',
  calling_tool: (info) => {
    const prefix = info.total ? `[${info.total}个工具] ` : ''
    if (info.tool === 'search_knowledge_base' && info.query) {
      const q = Array.isArray(info.query) ? info.query.join(', ') : info.query
      return `${prefix}正在检索知识库: ${q}…`
    }
    if (info.tool === 'read_full_document' && info.filename) {
      return `${prefix}正在阅读: ${info.filename}…`
    }
    if ((info.tool === 'read_knowledge_base_document' || info.tool === 'read_session_document') && info.filename) {
      return `${prefix}正在阅读: ${info.filename}…`
    }
    if (info.tool === 'web_search' && info.query) {
      const q = Array.isArray(info.query) ? info.query[0] : info.query
      return `${prefix}正在联网搜索: ${q}…`
    }
    const toolNames = {
      search_knowledge_base: `${prefix}正在检索知识库…`,
      read_knowledge_base_document: `${prefix}正在阅读知识库文档…`,
      read_session_document: `${prefix}正在阅读文档全文…`,
      web_search: `${prefix}正在联网搜索…`,
    }
    return toolNames[info.tool] || `${prefix}正在调用工具: ${info.tool}…`
  },
  tool_result: (info) => {
    if (info.chunks !== undefined) {
      return `✅ 检索完成，找到 ${info.chunks} 条结果`
    }
    if (info.tool === 'web_search') {
      return `✅ 联网搜索完成`
    }
    if (info.tool === 'read_full_document') {
      return `✅ 文档阅读完成`
    }
    if (info.tool === 'read_knowledge_base_document' || info.tool === 'read_session_document') {
      return `✅ 文档阅读完成`
    }
    if (info.tool === 'ask_user_for_clarification') {
      return '❓ 需要向您提问'
    }
    return ''
  },
}

const sendQuestion = async (payload) => {
  const text = (payload && payload.text || '').trim()
  const images = payload && payload.images || []
  // 必须有消息正文（纯图片不支持，需附上文字说明）
  if (!text || isLoading.value) return

  // 新一轮开始：清掉上一轮遗留的任务清单悬浮面板
  todolistItems.value = []

  // 确保会话已创建（上传图片需要挂在当前会话目录 sessions/{user_id}/{session_id}/ 下）
  if (!currentSessionId.value) await createNewSession()

  // 附带剪贴板图片：先上传换取对象键，随问答带给模型做图文检索
  const imageKeys = images.length ? await uploadPastedImages(images) : []
  messages.value.push({
    role: 'user',
    content: text,
    _key: nextMsgKey(),
    _attachments: imageKeys.length ? imageKeys : undefined,
  })
  isLoading.value = true
  throttleScroll()

  // 立即推入占位 AI 消息，后续通过索引替换来更新（触发 Vue 数组响应式）
  messages.value.push({ role: 'ai', content: '', reasoning: '', _v: 0, _key: nextMsgKey() })
  const aiIndex = messages.value.length - 1
  contextUsage.value = null
  beginSse(aiIndex)

  try {
    await axios.post(
      '/api/query',
      { session_id: currentSessionId.value, question: text, stream: true, style: userStore.answerStyle, workflow: selectedWorkflow.value === '__auto__' ? null : selectedWorkflow.value, images: imageKeys.length ? imageKeys : undefined },
      {
        headers: { 'Content-Type': 'application/json' },
        responseType: 'text',
        onDownloadProgress: sseDownloadHandler(),
      }
    )
  } catch (error) {
    const ctx = sseCtx
    if (ctx) {
      ctx.content += '\n\n*[系统错误，请重试]*'
      ctx.version++
      messages.value[ctx.aiIndex] = {
        role: 'ai', content: ctx.content, reasoning: ctx.reasoning, _v: ctx.version,
      }
    }
    message.error('请求失败，请重试')
  } finally {
    isLoading.value = false
    finalizeSse()
    nextTick(() => messageListRef.value?.scrollToBottom())
  }
}

const stopGeneration = async () => {
  try {
    await axios.post('/api/query/cancel', { session_id: currentSessionId.value })
  } catch {
    // 忽略取消请求的异常
  }
}

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
    const res = await axios.post('/api/session_files/upload', formData, {
      headers: { 'X-Session-ID': sessionId },
    })
    if (res.data?.usage) documentUsage.value = res.data.usage
    await fetchDocuments()
    await fetchParseStatus()
    messages.value.push({ role: 'event', content: eventText('upload', [file.name]), _key: nextMsgKey() })
    throttleScroll()
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

// 会话切换时刷新该会话的暂存附件与解析状态
watch(currentSessionId, () => {
  parseStatus.value = {}
  todolistItems.value = []
  clarification.value = null
  clarifVisible.value = false
  fetchDocuments()
  fetchParseStatus()
})

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
  background-color: transparent;
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
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: rgba(24, 160, 88, 0.05);
  box-shadow: 0 1px 3px var(--color-shadow-card);
}
.todo-header {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--color-text-1);
}
.todo-list { display: flex; flex-direction: column; gap: 6px; }
.todo-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text-1);
}
.todo-item.done .todo-text {
  color: var(--color-text-3);
  text-decoration: line-through;
}
.todo-box { flex-shrink: 0; }
.todo-text { flex: 1; }
.todo-done-tag {
  font-size: 11px;
  color: #18a058;
  flex-shrink: 0;
}

/* 澄清选择框 */
.clarif-question {
  font-size: 14px;
  color: var(--color-text-1);
  margin-bottom: 12px;
  white-space: pre-wrap;
  line-height: 1.6;
}
</style>
