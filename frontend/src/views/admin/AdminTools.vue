<template>
  <div class="tools-page">
    <n-space justify="space-between" align="center" style="margin-bottom: 16px">
      <n-h2 style="margin: 0">工具管理</n-h2>
      <n-space align="center">
        <n-input
          v-model:value="searchKeyword" placeholder="搜索工具（名称/描述）" clearable
          style="width: 260px" @keydown.enter="doSearch" @clear="doSearch"
        >
          <template #prefix><n-icon :component="SearchOutline" /></template>
        </n-input>
        <n-popconfirm @positive-click="resetBuiltins" :positive-button-props="{ type: 'error' }">
          <template #trigger>
            <n-button title="系统工具将按 @tool 声明恢复，自定义工具不受影响">
              <template #icon><n-icon :component="RefreshOutline" /></template>重置系统工具
            </n-button>
          </template>
          确定将全部系统工具重置为 @tool 声明定义？会覆盖你对系统工具的所有修改（自定义工具不受影响）。
        </n-popconfirm>
        <n-button type="primary" @click="openAdd">
          <template #icon><n-icon :component="AddOutline" /></template>新增工具
        </n-button>
      </n-space>
    </n-space>

    <n-data-table
      :columns="columns" :data="store.toolsData" :loading="store.loading"
      :bordered="true" :single-line="false" size="small" :row-key="(r) => r.name"
      :max-height="560"
    />
    <n-space justify="center" style="margin-top: 16px">
      <n-pagination
        v-model:page="page" :page-size="pageSize" :item-count="store.toolsTotal"
        :page-slot="7" show-size-picker :page-sizes="pageSizes"
        @update:page="refresh" @update:page-size="changeSize"
      />
      <n-text depth="3" style="font-size: 12px; line-height: 32px">共 {{ store.toolsTotal }} 个</n-text>
    </n-space>

    <!-- 新增 / 编辑弹窗 -->
    <n-modal
      v-model:show="showModal" preset="card"
      :title="editingName ? `编辑工具：${editingName}` : '新增工具'"
      style="width: 880px"
    >
      <div class="edit-body">
        <!-- 基本信息 -->
        <div class="edit-card">
          <div class="card-title">基本信息</div>
          <div class="field">
            <label class="field-label">名称</label>
            <n-input v-model:value="form.name" :disabled="!!editingName" placeholder="如：echo_tool" />
          </div>
          <div class="field" style="margin-top: 12px">
            <label class="field-label">功能描述（只填首段，Args/Returns 由下方参数自动生成）</label>
            <n-input v-model:value="form.description" type="textarea" :rows="3" placeholder="一句话说明工具用途" />
          </div>
        </div>

        <!-- 输入参数 -->
        <div class="edit-card">
          <div class="card-title-row">
            <span class="card-title">输入参数</span>
            <n-text depth="3" class="card-hint">决定 LLM 如何调用此工具（保存时组为 JSON Schema）</n-text>
            <n-button size="tiny" type="primary" ghost @click="inputParams.push({ name: '', type: 'string', required: false, description: '' })">
              <template #icon><n-icon :component="AddOutline" /></template>添加
            </n-button>
          </div>
          <div v-if="inputParams.length" class="param-table grid-in">
            <div class="param-row param-head">
              <span>参数名</span><span>类型</span><span>必填</span><span>说明</span><span></span>
            </div>
            <div v-for="(p, i) in inputParams" :key="i" class="param-row">
              <n-input v-model:value="p.name" placeholder="如：query" />
              <n-select v-model:value="p.type" :options="paramTypeOptions" />
              <n-switch v-model:value="p.required" size="small" />
              <n-input v-model:value="p.description" placeholder="参数用途说明" />
              <n-button size="tiny" quaternary circle type="error" @click="inputParams.splice(i, 1)">
                <template #icon><n-icon :component="TrashOutline" /></template>
              </n-button>
            </div>
          </div>
          <n-empty v-else description="暂无输入参数" size="small" style="padding: 6px 0" />
          <details class="schema-preview">
            <summary>查看生成的参数 Schema（LLM 收到的 JSON）</summary>
            <pre class="tool-desc-block">{{ schemaPreview }}</pre>
          </details>
        </div>

        <!-- 执行代码 -->
        <div class="edit-card">
          <div class="card-title">执行代码</div>
          <div class="field">
            <div class="code-toolbar">
              <label class="field-label" style="margin: 0">handler 代码</label>
              <div class="toolbar-actions">
                <n-button size="tiny" quaternary @click="downloadSourceTemplate">下载模板</n-button>
                <input ref="sourceInput" type="file" accept=".py" style="display: none" @change="onSourcePicked" />
                <n-button size="tiny" type="primary" ghost :disabled="!form.name" @click="sourceInput?.click()">上传 .py 源码</n-button>
              </div>
            </div>
            <n-input v-model:value="form.code" type="textarea" :rows="8" class="mono" placeholder="def handle(args, ctx):\n    return '结果'" />
            <n-text v-if="isModuleTool" depth="3" style="font-size: 12px; display: block; margin-top: 6px">
              已关联自定义源码（custom_tools.{form.name}.py），运行时按文件模块加载；保存会同步此编辑内容到文件。
            </n-text>
          </div>
        </div>

        <!-- 启停 / 并发 -->
        <div class="edit-card switches">
          <n-switch v-model:value="enabled" :checked-value="true" :unchecked-value="false">
            <template #checked>启用</template>
            <template #unchecked>停用</template>
          </n-switch>
          <n-switch v-model:value="concurrentSafe" :checked-value="true" :unchecked-value="false">
            <template #checked>可并行</template>
            <template #unchecked>串行</template>
          </n-switch>
        </div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showModal = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 试跑弹窗 -->
    <n-modal v-model:show="showTest" preset="card" style="width: 720px">
      <template #header>
        <div class="test-header">
          <div class="test-title-row">
            <n-icon :component="RocketOutline" size="20" class="test-icon" />
            <n-text strong style="font-size: 16px">工具：{{ testingName }}</n-text>
            <n-tag size="small" :bordered="false" type="info">{{ testParamHint }}</n-tag>
          </div>
        </div>
      </template>

      <div class="test-body">
        <!-- 参数区 -->
        <template v-if="formMode === 'schema'">
          <div v-if="metaFields.length" class="section-title">参数</div>
          <n-form label-placement="top" size="small" :model="testForm">
            <n-grid v-if="metaFields.length" :cols="2" :x-gap="18" :y-gap="28" responsive="screen" item-responsive class="test-param-grid">
              <n-grid-item v-for="f in metaFields" :key="f.key" :span="(f.input === 'list' || f.input === 'json') ? 2 : 1">
                <n-form-item :label="f.label" :required="f.required" :show-feedback="false">
                  <n-input v-if="f.input === 'text'" v-model:value="testForm[f.key]" :placeholder="f.placeholder" clearable style="flex: 1" />
                  <n-tooltip v-if="f.input === 'text'" trigger="hover">
                    <template #trigger>
                      <n-button size="small" quaternary @click="pickImage(f.key, null)">
                        <template #icon><n-icon :component="ImageOutline" /></template>
                      </n-button>
                    </template>
                    上传图片，自动填入对象键（供 OCR / 图片检索参数）
                  </n-tooltip>
                  <n-input-number v-else-if="f.input === 'number'" v-model:value="testForm[f.key]" style="width: 100%" :placeholder="f.placeholder" />
                  <n-switch v-else-if="f.input === 'switch'" v-model:value="testForm[f.key]" :checked-value="true" :unchecked-value="false" />
                  <n-select v-else-if="f.input === 'select'" v-model:value="testForm[f.key]" :options="f.options" :placeholder="f.placeholder" clearable />
                  <div v-else-if="f.input === 'list'" class="list-field">
                    <div v-for="(item, i) in (testForm[f.key] || [])" :key="i" class="list-row">
                      <n-input v-if="f.itemKind === 'string'" v-model:value="testForm[f.key][i]" placeholder="字符串 / 图片对象键" style="flex: 1" />
                      <n-button v-if="f.itemKind === 'string'" size="tiny" quaternary @click="pickImage(f.key, i)">
                        <template #icon><n-icon :component="ImageOutline" /></template>
                      </n-button>
                      <n-input-number v-else-if="f.itemKind === 'number'" v-model:value="testForm[f.key][i]" style="width: 100%" placeholder="数字" />
                      <n-select v-else-if="f.itemKind === 'select'" v-model:value="testForm[f.key][i]" :options="f.itemOptions" placeholder="请选择" />
                      <n-switch v-else-if="f.itemKind === 'switch'" v-model:value="testForm[f.key][i]" />
                      <n-input v-else type="textarea" v-model:value="testForm[f.key][i]" class="mono" :rows="1" placeholder="JSON 元素" />
                      <n-button size="tiny" quaternary circle type="error" @click="removeListItem(f.key, i)">
                        <template #icon><n-icon :component="TrashOutline" /></template>
                      </n-button>
                    </div>
                    <n-button size="tiny" quaternary @click="addListItem(f.key, f.itemKind, f.itemOptions)">
                      <template #icon><n-icon :component="AddOutline" /></template>添加一项
                    </n-button>
                  </div>
                  <n-input v-else type="textarea" v-model:value="testForm[f.key]" class="mono" :rows="2" :placeholder="f.placeholder" />
                </n-form-item>
              </n-grid-item>
            </n-grid>
            <n-empty v-else description="该工具无需参数" style="padding: 12px 0" />
          </n-form>
        </template>
        <template v-else>
          <div class="section-title">参数</div>
          <n-input v-model:value="testArgs" type="textarea" :rows="4" class="mono" placeholder='{"query": "苹果公司 2024 财报"}' />
        </template>

        <!-- 结果区 -->
        <div class="section-title" style="margin-top: 18px">执行结果</div>
        <div class="result-box">
          <n-input v-model:value="testResult" type="textarea" autosize class="mono" readonly placeholder="运行后显示…" />
        </div>
      </div>

      <template #footer>
        <n-space justify="space-between" align="center" style="width: 100%">
          <n-text depth="3" style="font-size: 12px">留空的参数不会传给工具（必填项用 Schema 默认值兜底）</n-text>
          <n-space>
            <n-button @click="showTest = false">关闭</n-button>
            <n-button type="primary" :loading="testingLoading" @click="runTest">运行</n-button>
          </n-space>
        </n-space>
      </template>
    </n-modal>
  </div>

  <!-- 测试页：图片参数上传通道（隐藏文件选择） -->
  <input ref="imgFileInput" type="file" accept="image/*" style="display:none" @change="onImgFile" />
</template>

<script setup>
import { computed, h, onMounted, reactive, ref } from 'vue'
import {
  NButton, NIcon, NSpace, NDataTable, NModal, NForm, NFormItem, NInput,
  NInputNumber, NTag, NSwitch, NH2, NPagination, NText, NPopconfirm,
  NSelect, NEmpty, NTooltip, useMessage,
} from 'naive-ui'
import { AddOutline, PencilOutline, TrashOutline, PlayOutline, RefreshOutline, RocketOutline, ConstructOutline, SearchOutline, ImageOutline } from '@vicons/ionicons5'
import { useAdminStore } from '@/stores/admin'

const store = useAdminStore()
const message = useMessage()

const page = ref(1)
const pageSize = ref(20)
const pageSizes = [10, 20, 50, 100, 200]
const searchKeyword = ref('')

const showModal = ref(false)
const editingName = ref('')
const enabled = ref(true)
const concurrentSafe = ref(false)
const saving = ref(false)
const isModuleTool = ref(false)

const form = reactive({ name: '', description: '', handler_module: '', code: '' })

// ── 动态参数编辑器（输入参数 → JSON Schema；输出参数 → 文档展示） ──
const paramTypeOptions = [
  { label: 'string', value: 'string' },
  { label: 'number', value: 'number' },
  { label: 'integer', value: 'integer' },
  { label: 'boolean', value: 'boolean' },
  { label: 'array', value: 'array' },
  { label: 'object', value: 'object' },
]
const inputParams = ref([])    // { name, type, required, description }
const schemaPreview = computed(() => JSON.stringify(assembleParameters(), null, 2))

function parseSchemaRows(parameters) {
  let schema
  try { schema = typeof parameters === 'string' ? JSON.parse(parameters) : parameters } catch { schema = {} }
  const props = schema?.properties || {}
  const req = new Set(schema?.required || [])
  return Object.keys(props).map(k => ({
    name: k,
    type: props[k].type || 'string',
    required: req.has(k),
    description: props[k].description || '',
  }))
}

function assembleParameters() {
  const properties = {}
  const required = []
  for (const p of inputParams.value) {
    const name = (p.name || '').trim()
    if (!name) continue
    const type = p.type || 'string'
    const prop = { type }
    if (type === 'array') prop.items = { type: 'string' }
    if (p.description && p.description.trim()) prop.description = p.description.trim()
    properties[name] = prop
    if (p.required) required.push(name)
  }
  return { type: 'object', properties, required }
}

function firstParagraph(desc) {
  // 描述首段（截到 Args:/Returns: 前，去掉换行压成一段）
  if (!desc) return ''
  return String(desc)
    .split(/\n\s*(?:Args|Returns):/)[0]
    .split('\n').map(l => l.trim()).filter(Boolean).join(' ')
}

function openAdd() {
  editingName.value = ''
  enabled.value = true
  concurrentSafe.value = false
  isModuleTool.value = false
  inputParams.value = []
  Object.assign(form, {
    name: '', description: '',
    handler_module: '', code: 'def handle(args, ctx):\n    return "工具执行结果"',
  })
  showModal.value = true
}

function openEdit(row) {
  editingName.value = row.name
  enabled.value = row.enabled
  concurrentSafe.value = !!row.concurrent_safe
  inputParams.value = parseSchemaRows(row.parameters)
  isModuleTool.value = !!(row.handler_module || '').startsWith('custom_tools.')
  if (isModuleTool.value) {
    Object.assign(form, {
      name: row.name,
      description: firstParagraph(row.description),
      handler_module: row.handler_module,
      code: '',
    })
    store.fetchToolSource(row.name).then((res) => { if (form.name === row.name) form.code = res.code || '' }).catch(() => {})
  } else {
    Object.assign(form, {
      name: row.name,
      description: firstParagraph(row.description),
      handler_module: row.handler_module || '',
      code: row.code,
    })
  }
  showModal.value = true
}

const sourceInput = ref(null)

function downloadSourceTemplate() {
  const content = `# ============================================
# 自定义工具源码模板（custom_tools 模块）
# ============================================
# 规则：
#   1. 必须定义 handle(args, ctx) 函数，并返回字符串；
#   2. args: 工具参数字典（对应表单里配置的输入参数，键名一致）；
#   3. ctx: 工具运行时上下文（可用 ctx.session_id / ctx.partition /
#      ctx.data_dir / ctx.cache / ctx.config 等）；
#   4. 上传后保存为 custom_tools/{工具名}.py，运行时按文件模块加载。
#
# 按需修改下面的示例即可。
# ============================================

def handle(args, ctx):
    # 读取输入参数（与你配置的输入参数名一致）
    query = args.get("query", "")

    # 使用运行时上下文：当前会话 ID 等
    session_id = getattr(ctx, "session_id", "") or ""
    partition = getattr(ctx, "partition", "") or ""

    # 业务逻辑…（这里只做演示）
    header = f"[会话:{session_id} / 分区:{partition}]"
    if not query:
        return f"{header}（未提供 query 参数）"
    return f"{header} 针对「{query}」得到结果：示例返回内容"
`
  const blob = new Blob([content], { type: 'text/x-python' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'custom_tool_template.py'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function onSourcePicked(e) {
  const el = e.target
  const file = el.files && el.files[0]
  if (!file) return
  if (!(form.name || '').trim()) { message.error('请先填写工具名称'); el.value = ''; return }
  saveSourceFile(el, file)
}

async function saveSourceFile(el, file) {
  try {
    const res = await store.uploadToolSource(form.name.trim(), file)
    form.handler_module = res.module
    form.code = res.code
    isModuleTool.value = true
    message.success('源码已上传并校验（需保存后生效）')
  } catch (e) {
    message.error(e.response?.data?.detail || e.message)
  } finally {
    if (el) el.value = ''   // 允许重复选择同一文件
  }
}

async function save() {
  if (!(form.name || '').trim()) { message.error('请输入工具名称'); return }
  if (!(form.code || '').trim()) { message.error('请输入 handler 代码，或先上传 .py 源码'); return }
  const seen = new Set()
  for (const p of inputParams.value) {
    const n = (p.name || '').trim()
    if (!n) { message.error('存在未命名的输入参数，请填写或删除'); return }
    if (seen.has(n)) { message.error(`输入参数名称重复：${n}`); return }
    seen.add(n)
  }
  saving.value = true
  try {
    let code = form.code
    let handlerModule = form.handler_module || null
    if (isModuleTool.value) {
      // 把当前编辑的源码同步到 custom_tools/{name}.py，再以函数名入 DB
      const blob = new Blob([form.code || ''], { type: 'text/x-python' })
      const f = new File([blob], `${form.name.trim()}.py`, { type: 'text/x-python' })
      await store.uploadToolSource(form.name.trim(), f)
      handlerModule = `custom_tools.${form.name.trim()}`
      code = 'handle'
    }
    const payload = {
      description: form.description.trim(),
      parameters: assembleParameters(),
      code,
      handler_module: handlerModule,
      enabled: enabled.value,
      concurrent_safe: concurrentSafe.value,
    }
    if (editingName.value) {
      await store.updateTool(editingName.value, payload)
      message.success('工具已更新，注册表已重载')
    } else {
      await store.createTool({ ...payload, name: form.name })
      message.success('工具已创建，注册表已重载')
    }
    showModal.value = false
    await refresh()
  } catch (e) {
    message.error(e.response?.data?.detail || e.message)
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row, value) {
  try {
    await store.updateTool(row.name, { enabled: value })
    message.success(value ? '已启用' : '已停用')
    await refresh()
  } catch (e) {
    message.error(e.response?.data?.detail || e.message)
  }
}

async function toggleConcurrent(row, value) {
  try {
    await store.updateTool(row.name, { concurrent_safe: value })
    message.success(value ? '已标记为可并行' : '已改为串行')
    await refresh()
  } catch (e) {
    message.error(e.response?.data?.detail || e.message)
  }
}

async function remove(row) {
  try {
    await store.deleteTool(row.name)
    message.success(`工具 ${row.name} 已删除`)
    await refresh()
  } catch (e) {
    message.error(e.response?.data?.detail || e.message)
  }
}

async function refresh() {
  try { await store.fetchTools(page.value, pageSize.value, searchKeyword.value) } catch (e) { message.error(e.message) }
}
function changeSize(size) { pageSize.value = size; page.value = 1; refresh() }
function doSearch() { page.value = 1; refresh() }

async function resetBuiltins() {
  try {
    const r = await store.resetBuiltinTools()
    message.success(`系统工具已重置：更新 ${r.updated || 0} / 新增 ${r.inserted || 0}`)
    await refresh()
  } catch (e) {
    message.error(e.response?.data?.detail || e.message)
  }
}

// ── 试跑 ──
const showTest = ref(false)
const testingName = ref('')
const testArgs = ref('{}')
const testResult = ref('')
const testingLoading = ref(false)
const formMode = ref('schema')      // schema=动态表单；raw=原 JSON 输入（兜底）
const metaFields = ref([])          // [{key,label,input,options,required,default,typeLabel}]
const testForm = reactive({})
const testParamHint = computed(() =>
  metaFields.value.length ? `${metaFields.value.length} 个参数 (${metaFields.value.filter(f => f.required).length} 必填)` : '无需参数'
)

const _TYPE_LABEL = {
  string: 'string', integer: 'integer', number: 'number', boolean: 'boolean',
  array: 'array', object: 'object', null: 'null',
}

function buildTestForm(row) {
  let schema
  try {
    schema = (typeof row.parameters === 'string' ? JSON.parse(row.parameters) : row.parameters) || {}
  } catch {
    return null
  }
  const props = schema.properties || {}
  const required = new Set(schema.required || [])
  const fields = []
  for (const [key, _prop] of Object.entries(props)) {
    // langchain 对 Optional 参数生成 anyOf/oneOf（[实型, null]），拍平成实际类型再渲染
    let prop = { ..._prop }
    for (const kind of ['anyOf', 'oneOf']) {
      const variants = prop[kind] || _prop[kind]
      if (Array.isArray(variants)) {
        const pick = variants.find(v => v && v.type !== 'null') || variants[0] || {}
        prop = { ...prop, ...pick }
        delete prop[kind]
        break
      }
    }
    const type = Array.isArray(prop?.enum) ? 'string' : (prop?.type || 'json')
    let input = 'text'
    let options = null
    let itemKind = null       // 数组元素类型：string/number/boolean/select/json
    let itemOptions = null
    if (Array.isArray(prop?.enum)) {
      input = 'select'
      options = prop.enum.map(v => ({ label: String(v), value: v }))
    } else if (type === 'integer' || type === 'number') input = 'number'
    else if (type === 'boolean') input = 'switch'
    else if (type === 'array') {
      input = 'list'
      let items = prop?.items || {}
      for (const kind of ['anyOf', 'oneOf']) {
        const variants = items[kind]
        if (Array.isArray(variants)) {
          const pick = variants.find(v => v && v.type !== 'null') || variants[0] || {}
          items = { ...items, ...pick }
          break
        }
      }
      if (Array.isArray(items.enum)) {
        itemKind = 'select'
        itemOptions = items.enum.map(v => ({ label: String(v), value: v }))
      } else if (items.type === 'integer' || items.type === 'number') itemKind = 'number'
      else if (items.type === 'boolean') itemKind = 'switch'
      else if (items.type === 'object') itemKind = 'json'
      else itemKind = 'string'
    } else if (type === 'object') input = 'json'

    let def = prop?.default
    if (def === undefined) {
      def = type === 'boolean' ? false
        : type === 'array' ? []
        : type === 'object' ? '{}'
        : (type === 'integer' || type === 'number') ? null
        : ''
    }
    const req = required.has(key)
    let ph
    if (input === 'text') ph = req ? `请输入 ${key}` : `${key}（可选）`
    else if (input === 'number') ph = '留空 = 不传'
    else if (input === 'select') ph = req ? '请选择' : '可选'
    else if (input === 'json') ph = 'JSON'
    else ph = ''
    fields.push({
      key,
      label: prop?.title || key,
      input,
      options,
      itemKind,
      itemOptions,
      required: req,
      default: def,
      placeholder: ph,
      typeLabel: _TYPE_LABEL[type] || type,
    })
  }
  return fields
}

function openTest(row) {
  testingName.value = row.name
  const fields = buildTestForm(row)
  metaFields.value = fields || []
  formMode.value = fields ? 'schema' : 'raw'
  for (const k of Object.keys(testForm)) delete testForm[k]
  if (fields) for (const f of fields) testForm[f.key] = f.default
  testArgs.value = '{}'
  testResult.value = ''
  showTest.value = true
}

function addListItem(key, itemKind, itemOptions) {
  const arr = testForm[key] || (testForm[key] = [])
  let v
  if (itemKind === 'number') v = null
  else if (itemKind === 'switch') v = false
  else if (itemKind === 'select') v = itemOptions?.[0]?.value ?? ''
  else v = ''
  arr.push(v)
}

function removeListItem(key, i) {
  testForm[key].splice(i, 1)
}

// ── 测试页：图片参数上传通道 ──
const imgFileInput = ref(null)
const imgTarget = ref(null)   // { key, index } index 为 null 表示普通文本参数
function pickImage(key, index = null) {
  imgTarget.value = { key, index }
  imgFileInput.value?.click()
}
async function onImgFile(e) {
  const file = e.target.files && e.target.files[0]
  if (e.target) e.target.value = ''
  if (!file || !imgTarget.value) return
  try {
    const key = await store.uploadTestImage(file)
    if (!key) { message.error('图片上传失败'); return }
    const t = imgTarget.value
    if (t.index === null || t.index === undefined) {
      testForm[t.key] = key
    } else {
      const arr = testForm[t.key] || (testForm[t.key] = [])
      if (t.index < arr.length) arr[t.index] = key
      else arr.push(key)
    }
    message.success('图片已上传，已填入对象键')
  } catch (err) {
    message.error(err?.message || '上传失败')
  } finally {
    imgTarget.value = null
  }
}

async function runTest() {
  let args = {}
  if (formMode.value === 'schema') {
    for (const f of metaFields.value) {
      const v = testForm[f.key]
      if (f.input === 'list') {
        const items = []
        let bad = false
        for (const raw of (v || [])) {
          if (raw === null || raw === undefined || raw === '') continue
          if (f.itemKind === 'number') items.push(Number(raw))
          else if (f.itemKind === 'switch') items.push(!!raw)
          else if (f.itemKind === 'json') {
            try { items.push(JSON.parse(raw)) } catch { message.error(`「${f.label}」第 ${items.length + 1} 项不是合法 JSON`); bad = true; break }
          } else items.push(raw)
        }
        if (bad) return
        if (items.length || f.required) args[f.key] = items
        continue
      }
      if (v === null || v === undefined || v === '') {
        // 留空：必填项用默认值兜底，可选项不传
        if (f.required && v === null) {
          if (f.input === 'number') args[f.key] = f.default ?? 0
          else if (f.input !== 'switch') args[f.key] = f.default ?? ''
        }
        continue
      }
      if (f.input === 'number') args[f.key] = Number(v)
      else if (f.input === 'switch') args[f.key] = !!v
      else if (f.input === 'json') {
        try { args[f.key] = JSON.parse(v) } catch { message.error(`「${f.label}」不是合法 JSON`); return }
      } else args[f.key] = v
    }
  } else {
    try { args = JSON.parse(testArgs.value || '{}') } catch { message.error('参数必须是合法 JSON'); return }
  }
  testingLoading.value = true
  try {
    const res = await store.testTool(testingName.value, args)
    testResult.value = res?.result || '(无输出)'
  } catch (e) {
    testResult.value = ''
    message.error(e.response?.data?.detail || e.message)
  } finally {
    testingLoading.value = false
  }
}

// ── 表格列渲染辅助 ──
const columns = [
  {
    title: '名称', key: 'name', width: 230,
    render: (r) => h('div', { class: 'tool-name-cell' }, [
      h(NIcon, { component: ConstructOutline, size: 18, color: 'var(--color-primary)' }),
      h('div', { class: 'tool-name-info' }, [
        h(NText, { strong: true, style: 'font-size: 13px' }, { default: () => r.name }),
        h('div', { class: 'tool-name-sub' }, r.handler_module || '内联代码'),
      ]),
    ]),
  },
  {
    title: '描述', key: 'description', width: 320,
    render: (r) => h('pre', { class: 'tool-desc-block', title: r.description || undefined }, firstParagraph(r.description) || '-'),
  },
  {
    title: '启用', key: 'enabled', width: 70,
    render: (r) => h(NSwitch, { value: !!r.enabled, onUpdateValue: (v) => toggleEnabled(r, v) }),
  },
  {
    title: '并发', key: 'concurrent_safe', width: 70,
    render: (r) => h(NSwitch, { value: !!r.concurrent_safe, onUpdateValue: (v) => toggleConcurrent(r, v) }),
  },
  { title: '更新', key: 'updated_at', width: 175 },
  {
    title: '操作', key: 'actions', width: 210,
    render: (row) => h(NSpace, { size: 4 }, [
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openTest(row) },
        { icon: () => h(NIcon, { component: PlayOutline }), default: () => '测试' }),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => openEdit(row) },
        { icon: () => h(NIcon, { component: PencilOutline }), default: () => '编辑' }),
      h(NPopconfirm, { onPositiveClick: () => remove(row) },
        { trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' },
            { icon: () => h(NIcon, { component: TrashOutline }), default: () => '删除' }),
          default: () => `删除工具 ${row.name}？` }),
    ]),
  },
]

onMounted(refresh)
</script>

<style scoped>
.tools-page { padding: 4px; }
.mono :deep(textarea) { font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px; }
.list-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}
.list-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}
.list-row > * { flex: 1; }
.list-row > button { flex: none; }
/* ── 新增/编辑弹窗（卡片分区 + 表格化参数编辑器） ── */
.edit-body { display: flex; flex-direction: column; gap: 14px; max-height: 68vh; overflow-y: auto; padding-right: 4px; }
.edit-card {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 14px 16px;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--color-text-1);
}
.card-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.card-title-row .card-title { margin-bottom: 0; }
.card-hint { font-size: 12px; flex: 1; }
.field-label {
  display: block;
  font-size: 13px;
  color: var(--color-text-2);
  margin-bottom: 6px;
}
.code-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.toolbar-actions { display: flex; align-items: center; gap: 4px; }
.param-table {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  overflow: hidden;
}
.param-table > .param-row {
  display: grid;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
}
.param-table.grid-in > .param-row { grid-template-columns: 150px 120px 64px 1fr 36px; }
.param-table > .param-head {
  background: var(--color-primary-bg);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-2);
  padding: 6px 10px;
}
.param-table > .param-row:not(.param-head) { border-top: 1px solid var(--color-border); }
.schema-preview { margin-top: 10px; }
.schema-preview summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--color-text-2);
  user-select: none;
}
.schema-preview pre { margin-top: 8px; }
.edit-card.switches { display: flex; gap: 24px; align-items: center; }
.test-header { margin-top: -4px; }
.test-title-row { display: flex; align-items: center; gap: 8px; }
.test-icon { color: var(--color-primary); }
.test-body { display: flex; flex-direction: column; }
.test-param-grid :deep(.n-form-item) { margin-bottom: 6px; }
.test-param-grid :deep(.n-form-item .n-form-item__label) {
  margin-bottom: 8px;
  margin-top: 2px;
  line-height: 1.4;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-3);
  margin: 0 0 10px;
}
.result-box {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 8px;
  background: var(--color-modal-bg);
}
.result-box .mono :deep(textarea) { font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px; }
</style>

<!-- 表格 h() 渲染的单元格元素不带 scoped 属性，需要非 scoped 全局样式 -->
<style>
.tool-name-cell { display: flex; align-items: center; gap: 8px; }
.tool-name-info { display: flex; flex-direction: column; line-height: 1.35; min-width: 0; }
.tool-name-sub {
  font-size: 11px;
  color: var(--color-text-3);
  font-family: 'JetBrains Mono', Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tool-desc-block {
  margin: 0;
  padding: 4px 6px;
  max-height: 150px;
  max-width: 100%;
  box-sizing: border-box;
  overflow: auto;             /* 垂直 + 水平滚动条，杜绝溢出 */
  background: transparent;      /* 明色主题：透明背景 */
  color: #4d3a2c;             /* 暖调深褐，适配淡橘背景 */
  border: 1px solid rgba(240, 210, 166, 0.8);
  border-radius: 4px;
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 11px;            /* 字体缩小，减少换行 */
  line-height: 1.5;
  white-space: pre-wrap;      /* 摘要一段自动换行 */
  word-break: break-word;
}
[data-theme="dark"] .tool-desc-block {
  background: var(--color-code-bg);      /* 应用标准深色代码块配色 */
  color: var(--color-code-text);
  border-color: #3f3a36;
}
</style>