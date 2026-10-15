// src/stores/chat.js
// 每个会话独立的聊天状态 + 流式运行时。
//
// 放在 store（而非组件）里，因此：
//   - 切换会话 / 打开管理后台（卸载 Home）都不会中断生成；
//   - 每个会话可各自后台生成，切回来即可看到（含正在流式的过程）。
import { reactive } from 'vue'
import { defineStore } from 'pinia'
import axios from '@/http/interceptor'

let _seq = 0
const nextKey = () => `m${++_seq}`

// Agent 状态文案（tool call / thinking）
const statusLabels = {
  thinking: '深度思考中…',
  calling_tool: (info) => {
    const prefix = info.total ? `[${info.total}个工具] ` : ''
    if (info.tool === 'search_knowledge_base' && info.query) {
      const q = Array.isArray(info.query) ? info.query.join(', ') : info.query
      return `${prefix}正在检索知识库: ${q}…`
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
      create_deliverable: `${prefix}正在生成 PDF 交付物…`,
      list_deliverable_templates: `${prefix}正在查看交付物模板…`,
    }
    return toolNames[info.tool] || `${prefix}正在调用工具: ${info.tool}…`
  },
  tool_result: (info) => {
    if (info.chunks !== undefined) return `✅ 检索完成，找到 ${info.chunks} 条结果`
    if (info.tool === 'web_search') return '✅ 联网搜索完成'
    if (info.tool === 'read_knowledge_base_document' || info.tool === 'read_session_document') {
      return '✅ 文档阅读完成'
    }
    if (info.tool === 'ask_user_for_clarification') return '需要你的确认'
    if (info.tool === 'create_deliverable') return '✅ 交付物已生成'
    return ''
  },
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

// 用户消息清洗：剥离后端注入的“附带图片”说明块，还原为可见文本 + 附带图片标注
function cleanUserMessage(content = '') {
  const text = String(content || '')
  const m = text.match(/\n\n\[用户附带了图片，图片对象键：(.*?)。/)
  if (!m) return { role: 'user', content: text }
  let attach
  try {
    const arr = JSON.parse(m[1])
    attach = Array.isArray(arr) && arr.length ? arr : undefined
  } catch {
    attach = undefined
  }
  return { role: 'user', content: text.slice(0, m.index), _attachments: attach }
}

function _isAborted(err) {
  return err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError'
}

function newState() {
  return {
    messages: [],
    historyLoaded: false,
    isLoading: false,
    contextUsage: null,
    agentStatus: { visible: false, text: '' },
    todolistItems: [],
    clarification: null,
    clarifVisible: false,
    clarifChoice: '',
    clarifCustom: '',
    clarifSubmitting: false,
    parseStatus: {},
    documents: [],
    usage: { current_mb: 0, max_mb: 0, limit_enabled: false },
    abort: null,   // AbortController（仅会话删除等硬中止用）
    rev: 0,        // 每次刷新自增，供视图做滚动等副作用
  }
}

export const useChatStore = defineStore('chat', () => {
  const sessions = reactive({})          // sid -> 会话状态（响应式）
  const sse = new Map()                  // sid -> { buffer, processed, ctx }

  function ensure(sid) {
    if (!sid) return null
    if (!sessions[sid]) sessions[sid] = reactive(newState())
    return sessions[sid]
  }

  function _sse(sid) {
    if (!sse.has(sid)) sse.set(sid, { buffer: '', processed: 0, ctx: null })
    return sse.get(sid)
  }

  // ── SSE 增量解析（绑定到具体会话的上下文） ──

  function beginSse(sid, aiIndex) {
    const st = ensure(sid)
    const s = _sse(sid)
    s.buffer = ''
    s.processed = 0
    s.ctx = {
      aiIndex,
      key: st.messages[aiIndex]?._key,
      content: '', reasoning: '', version: 0, chunk: '', reasoningDirty: false,
    }
  }

  function flushSse(sid, force = false) {
    const st = ensure(sid)
    const s = _sse(sid)
    const ctx = s.ctx
    if (!ctx) return
    if (st.messages[ctx.aiIndex]?._key !== ctx.key) {   // 目标消息已不在（历史被替换）：丢弃
      s.ctx = null
      return
    }
    if (ctx.chunk) {
      ctx.content += ctx.chunk
      ctx.chunk = ''
      ctx.version++
    }
    if (ctx.version || ctx.reasoningDirty || force) {
      ctx.reasoningDirty = false
      st.messages[ctx.aiIndex] = {
        role: 'ai', content: ctx.content, reasoning: ctx.reasoning, _v: ctx.version, _key: ctx.key,
      }
      st.rev++
    }
  }

  function applySseContent(sid, content) {
    const st = ensure(sid)
    const s = _sse(sid)
    const ctx = s.ctx
    if (!ctx) return
    if (typeof content === 'string') { ctx.chunk += content; return }   // 旧格式纯字符串 token
    if (typeof content !== 'object' || !content) return

    if (content.type === 'status') {
      const label = statusLabels[content.status]
      if (content.status === 'thinking' || content.status === 'calling_tool') {
        st.agentStatus = {
          visible: true,
          text: typeof label === 'function' ? label(content) : (label || '处理中…'),
        }
      } else if (content.status === 'tool_result') {
        const summary = typeof label === 'function' ? label(content) : ''
        st.agentStatus = summary ? { visible: true, text: summary } : { visible: false, text: '' }
      } else if (content.status === 'ask_user') {
        st.clarification = {
          question: content.question || '',
          options: Array.isArray(content.options) ? content.options : [],
        }
        st.clarifChoice = ''
        st.clarifCustom = ''
        st.clarifVisible = true
      } else if (content.status === 'todolist') {
        st.todolistItems = Array.isArray(content.items) ? content.items : []
      } else if (content.status === 'cancelled') {
        const cancelMsg = { role: 'ai', content: '', _key: nextKey(), isCancelled: true }
        st.messages[ctx.aiIndex]
          ? Object.assign(st.messages[ctx.aiIndex], cancelMsg)
          : st.messages.push(cancelMsg)
        st.agentStatus = { visible: false, text: '' }
      }
      return
    }
    if (content.type === 'token') {
      st.agentStatus = { visible: false, text: '' }
      ctx.chunk += content.text || ''
      return
    }
    if (content.type === 'reasoning') {
      ctx.reasoning += content.text || ''
      ctx.reasoningDirty = true
      return   // 交由本次 download 的收尾 flushSse 统一刷新
    }
    if (content.type === 'deliverable') {
      st.messages.push({
        role: 'deliverable', id: content.id, title: content.title || '交付物',
        name: content.name || '', size: content.size || 0, _key: nextKey(),
      })
      st.rev++
      return
    }
    if (content.type === 'context') {
      const used = Number(content.used_chars) || 0
      const win = Number(content.window_chars) || 0
      st.contextUsage = { used, window: win, pct: win ? Math.round((used / win) * 100) : 0 }
    }
  }

  // axios onDownloadProgress 处理器：增量解析 SSE（只处理 \n\n 结束的完整事件）
  function sseDownloadHandler(sid) {
    return (progressEvent) => {
      const s = _sse(sid)
      const fullText = progressEvent.event.target.responseText || ''
      const newText = fullText.slice(s.processed)
      if (!newText) return
      s.processed = fullText.length
      s.buffer += newText
      const events = s.buffer.split('\n\n')
      s.buffer = events.pop() || ''
      for (const event of events) {
        for (const line of event.split('\n')) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const raw = trimmed.slice(5)
          if (!raw || raw === '[DONE]') continue
          let content
          try { content = JSON.parse(raw) } catch { content = raw }
          if (!content) continue
          applySseContent(sid, content)
        }
      }
      flushSse(sid, false)
    }
  }

  // 收尾：任务清单收纳进本轮 AI 消息 + 落定最终内容
  function finalizeSse(sid) {
    const st = ensure(sid)
    const s = _sse(sid)
    const ctx = s.ctx
    if (ctx && st.todolistItems && st.todolistItems.length) {
      const allDone = st.todolistItems.every(it => it.done)
      const mark = allDone ? '✅' : '📋'
      ctx.content += `\n\n---\n${mark} 任务清单（${allDone ? '全部完成' : '未全部完成'}）\n` +
        st.todolistItems.map(it => `- ${it.done ? '[x]' : '[ ]'} ${it.text}`).join('\n')
      ctx.version++
      st.todolistItems = []
    }
    flushSse(sid, true)
    s.buffer = ''
    s.ctx = null
  }

  // ── 历史 ──

  async function loadHistory(sid) {
    const st = ensure(sid)
    try {
      const response = await axios.get(`/api/history/${sid}`)
      if (response.status === 200) {
        const newMessages = []
        // 交付物事件写在「本轮回答」中间（工具执行时落库，回答在回合结束才落库）→
        // 先挂起，等整轮结束（出现下一轮的 user，或历史结束）再追加，
        // 这样与生成时"卡片在回答下方"的即时位置一致。
        const pendingDeliverables = []
        const flushDeliverables = () => {
          while (pendingDeliverables.length) newMessages.push(pendingDeliverables.shift())
        }
        for (const msg of response.data.history || []) {
          if (msg.type === 'event') {
            if (msg.event_type === 'deliverable') {
              const files = msg.files || []
              if (files[0]) {
                pendingDeliverables.push({
                  role: 'deliverable', id: files[0], title: files[1] || '交付物',
                  name: `${files[1] || '交付物'}.pdf`, size: Number(files[2]) || 0, _key: nextKey(),
                })
              }
              continue
            }
            const text = eventText(msg.event_type, msg.files)
            if (text) newMessages.push({ role: 'event', content: text, _key: nextKey() })
            continue
          }
          if (msg.type === 'turn') {
            let turnStarted = false
            for (const m of msg.messages || []) {
              if (m.role === 'user') {
                turnStarted = true
                newMessages.push({ ...cleanUserMessage(m.content), _key: nextKey() })
              } else if (m.role === 'assistant' && !m.tool_calls) {
                newMessages.push({ role: 'ai', content: m.content || '', _key: nextKey() })
              }
            }
            if (turnStarted) flushDeliverables()   // 新一轮开始 → 上一轮的交付物追加到此
            continue
          }
          if (msg.user == null && msg.assistant == null) continue
          newMessages.push(
            { role: 'user', content: msg.user || '', _key: nextKey() },
            { role: 'ai', content: msg.assistant || '', _key: nextKey() }
          )
          flushDeliverables()
        }
        flushDeliverables()

        // 老记录的事件里没存字节数 → 用交付物接口回填（顺带校正标题 / 文件名）
        const unknownSize = newMessages.filter((m) => m.role === 'deliverable' && !m.size)
        if (unknownSize.length) {
          try {
            const res = await axios.get('/api/deliverables', { params: { session_id: sid } })
            const byId = new Map((res.data?.deliverables || []).map((d) => [d.id, d]))
            for (const m of unknownSize) {
              const d = byId.get(m.id)
              if (!d) continue
              m.size = Number(d.size) || 0
              m.name = d.name || m.name
              m.title = d.title || m.title
            }
          } catch (e) {
            // 拿不到就按"未知大小"渲染（卡片不显示大小，也不显示 0）
          }
        }
        st.messages = newMessages
      } else {
        st.messages = []
      }
    } catch (e) {
      st.messages = []
    }
    st.historyLoaded = true
    st.rev++
  }

  // ── 生成（前台/后台一致，状态写入会话本身） ──

  async function send(sid, { text, imageKeys = [], style = null, workflow = null } = {}) {
    const st = ensure(sid)
    if (!sid || st.isLoading) return
    st.todolistItems = []
    st.messages.push({
      role: 'user',
      content: text,
      _key: nextKey(),
      _attachments: imageKeys.length ? imageKeys : undefined,
    })
    st.isLoading = true
    st.messages.push({ role: 'ai', content: '', reasoning: '', _v: 0, _key: nextKey() })
    const aiIndex = st.messages.length - 1
    st.contextUsage = null
    st.rev++
    beginSse(sid, aiIndex)

    const controller = new AbortController()
    st.abort = controller
    try {
      await axios.post(
        '/api/query',
        {
          session_id: sid, question: text, stream: true, style,
          workflow, images: imageKeys.length ? imageKeys : undefined,
        },
        {
          headers: { 'Content-Type': 'application/json' },
          responseType: 'text',
          signal: controller.signal,
          onDownloadProgress: sseDownloadHandler(sid),
        }
      )
    } catch (error) {
      if (!_isAborted(error)) {
        const ctx = _sse(sid).ctx
        if (ctx) { ctx.content += '\n\n*[系统错误，请重试]*'; flushSse(sid, true) }
      }
    } finally {
      if (st.abort === controller) {
        st.abort = null
        st.isLoading = false
        finalizeSse(sid)
        st.rev++
      }
    }
  }

  async function resume(sid, answer) {
    const st = ensure(sid)
    if (!sid || st.isLoading) return
    st.clarifVisible = false
    st.clarification = null
    st.messages.push({ role: 'user', content: answer, _key: nextKey() })
    st.messages.push({ role: 'ai', content: '', reasoning: '', _v: 0, _key: nextKey() })
    const aiIndex = st.messages.length - 1
    st.clarifSubmitting = true
    st.agentStatus = { visible: true, text: '正在继续生成…' }
    st.isLoading = true
    st.contextUsage = null
    st.rev++
    beginSse(sid, aiIndex)

    const controller = new AbortController()
    st.abort = controller
    try {
      await axios.post(
        '/api/query/resume',
        { session_id: sid, answer, stream: true },
        {
          headers: { 'Content-Type': 'application/json' },
          responseType: 'text',
          signal: controller.signal,
          onDownloadProgress: sseDownloadHandler(sid),
        }
      )
    } catch (e) {
      if (!_isAborted(e)) {
        const ctx = _sse(sid).ctx
        const errMsg = (e && e.response && e.response.data && e.response.data.detail) || (e && e.message) || '未知错误'
        if (ctx) { ctx.content += `\n\n*[继续生成失败：${errMsg}]*`; flushSse(sid, true) }
      }
    } finally {
      st.agentStatus = { visible: false, text: '' }
      st.clarifSubmitting = false
      if (st.abort === controller) {
        st.abort = null
        st.isLoading = false
        finalizeSse(sid)
        st.rev++
      }
    }
  }

  // 停止生成（温和）：通知后端取消，等待 cancelled 事件回传后收尾
  function stop(sid) {
    if (!sid) return
    axios.post('/api/query/cancel', { session_id: sid }).catch(() => {})
  }

  // 硬中止 + 丢弃会话状态（会话被删除时用）
  function drop(sid) {
    const st = sessions[sid]
    if (st?.abort) { try { st.abort.abort() } catch { /* ignore */ } }
    axios.post('/api/query/cancel', { session_id: sid }).catch(() => {})
    delete sessions[sid]
    sse.delete(sid)
  }

  // 追加一条事件提示消息（上传/删除附件等）
  function pushEvent(sid, type, files) {
    const st = ensure(sid)
    const text = eventText(type, files)
    if (st && text) {
      st.messages.push({ role: 'event', content: text, _key: nextKey() })
      st.rev++
    }
  }

  // ── 会话附件（按会话隔离，切走再回来仍保留） ──

  async function fetchDocuments(sid) {
    const st = ensure(sid)
    if (!sid) { return }
    try {
      const response = await axios.get('/api/session_files', { headers: { 'X-Session-ID': sid } })
      if (response.status === 200) {
        st.documents = (response.data.files || []).map((f) => ({
          name: f.name, size: f.size || 0, kind: f.kind || 'file',
        }))
        if (response.data.usage) st.usage = response.data.usage
      }
    } catch (error) {
      console.error('获取会话附件失败:', error)
    }
  }

  async function fetchParseStatus(sid) {
    const st = ensure(sid)
    if (!sid) return
    try {
      const res = await axios.get('/api/session_files/parse_status', { headers: { 'X-Session-ID': sid } })
      st.parseStatus = res.data?.files || {}
    } catch (error) {
      console.error('获取解析状态失败:', error)
    }
  }

  return {
    sessions, ensure, nextKey,
    loadHistory, send, resume, stop, drop, pushEvent,
    fetchDocuments, fetchParseStatus,
  }
})
