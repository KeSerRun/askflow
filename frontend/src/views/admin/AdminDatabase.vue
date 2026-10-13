<template>
  <div class="database-page">
    <n-h2 style="margin-top: 0">数据管理</n-h2>

    <n-tabs type="line" v-model:value="tab">
      <!-- 系统文档 -->
      <n-tab-pane name="system" tab="系统文档">
        <n-card :bordered="true" size="small" title="上传系统级文档（全局检索）">
          <n-upload
            multiple :show-file-list="false" @change="doUpload" :disabled="isUploading"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.gif,.doc,.docx,.ppt,.pptx,.xls,.xlsx"
          >
            <n-button type="primary" :loading="isUploading">选择文件并上传</n-button>
          </n-upload>
          <n-text depth="3" style="display: block; margin-top: 8px; font-size: 12px">
            支持 PDF / 图片 / Word / PPT / Excel（MinerU 解析）。选择后自动批量上传，可在下方查看逐文件进度。
          </n-text>

          <!-- 上传面板：已加载过一次即固定显示（避免异步数据未到时整块消失导致分页器闪没） -->
          <div v-if="rawLoaded || uploadTask" class="upload-panel" style="margin-top: 14px">
            <n-space justify="space-between" align="center">
              <n-text strong>上传任务</n-text>
              <n-space size="small" align="center">
                <n-button size="tiny" quaternary @click="loadRawFiles">刷新</n-button>
                <n-text depth="3" style="font-size: 12px">原始文件 {{ store.systemFilesTotal }} 个</n-text>
              </n-space>
            </n-space>

            <!-- 仅上传进行中显示进度 -->
            <template v-if="uploadTask?.status === 'processing'">
              <n-space align="center" style="margin-top: 10px">
                <n-tag :type="taskTagType" size="small">处理中</n-tag>
                <n-text depth="3" style="font-size: 12px">
                  成功 {{ uploadTask.success || 0 }} / 失败 {{ uploadTask.fail || 0 }} / 共 {{ uploadTask.total || 0 }}
                </n-text>
              </n-space>
              <n-progress type="line" :percentage="uploadPercent" :show-label="false" style="margin-top: 6px" />
            </template>

            <!-- 合并表：文件名 + 状态 + 操作（删除仅删原文件） -->
            <n-data-table
              v-if="queueRows.length" :columns="queueColumns" :data="queueRows"
              :bordered="false" :single-line="true" size="small" :pagination="false" style="margin-top: 10px"
            />
            <n-empty v-else description="暂无原始文件" style="padding: 16px 0" />

            <n-space v-if="store.systemFilesTotal > 0" justify="center" style="margin-top: 8px">
              <n-pagination
                v-model:page="rawPage" :page-size="rawPageSize" :item-count="store.systemFilesTotal"
                :page-slot="7" show-size-picker :page-sizes="pageSizes"
                @update:page="loadRawFiles" @update:page-size="changeRawSize"
              />
              <n-text depth="3" style="font-size: 12px; line-height: 32px">共 {{ store.systemFilesTotal }} 条</n-text>
            </n-space>
          </div>
        </n-card>

        <n-card title="已入库系统文档" :bordered="true" size="small" style="margin-top: 16px">
          <template #header-extra>
            <n-button size="small" quaternary @click="loadSystemDocs">刷新</n-button>
          </template>
          <n-data-table
            v-if="store.systemDocs.length"
            :columns="systemColumns" :data="store.systemDocs"
            :bordered="false" :single-line="true" size="small" :pagination="false"
          />
          <n-empty v-else description="暂无系统文档" style="padding: 20px 0" />
          <n-space v-if="store.systemDocsTotal > 0" justify="center" style="margin-top: 16px">
            <n-pagination
              v-model:page="systemPage" :page-size="systemPageSize" :item-count="store.systemDocsTotal"
              :page-slot="7" show-size-picker :page-sizes="pageSizes"
              @update:page="loadSystemDocs" @update:page-size="changeSystemSize"
            />
            <n-text depth="3" style="font-size: 12px; line-height: 32px">共 {{ store.systemDocsTotal }} 条</n-text>
          </n-space>
        </n-card>
      </n-tab-pane>

      <!-- 切块详情 -->
      <n-tab-pane name="chunks" tab="切块详情">
        <n-space style="margin-bottom: 16px" :wrap="true">
          <n-input v-model:value="chunkQuery" placeholder="搜索文本内容..." clearable style="width: 240px" @keydown.enter="searchChunks" />
          <n-select v-model:value="chunkType" :options="chunkTypeOptions" placeholder="选择类型" clearable style="width: 150px" @update:value="searchChunks" />
          <n-button type="primary" @click="searchChunks">搜索</n-button>
        </n-space>

        <n-data-table
          :columns="chunkColumns" :data="store.dbChunks?.items || []" :loading="store.loading"
          :bordered="true" :single-line="false" size="small" :max-height="500"
          :row-key="(row) => row.id" :pagination="false"
        />
        <n-space justify="center" style="margin-top: 16px">
          <n-pagination v-model:page="chunkPage" :page-size="chunkPageSize" :item-count="store.dbChunks?.total || 0" :page-slot="7" show-size-picker :page-sizes="pageSizes" @update:page="loadChunks" @update:page-size="changeChunkSize" />
          <n-text depth="3" style="font-size: 12px; line-height: 32px">共 {{ store.dbChunks?.total || 0 }} 条</n-text>
        </n-space>
      </n-tab-pane>

      <!-- 文档视图（MD 按页展示，每页标记分块） -->
      <n-tab-pane name="mdview" tab="文档视图">
        <n-card :bordered="true" size="small">
          <n-space :wrap="true" align="center" style="margin-bottom: 12px">
            <n-select
              v-model:value="mdSource" :options="mdDocOptions" filterable
              placeholder="选择要查看的文档" clearable style="width: 420px"
              @update:value="mdSource ? loadMdView() : (mdResult = null)"
            />
            <n-button type="primary" :disabled="!mdSource" :loading="mdLoading" @click="loadMdView">加载视图</n-button>
            <n-text v-if="mdResult?.available" depth="3" style="font-size: 12px">
              <template v-if="mdResult.paginated">共 {{ mdResult.pages.length }} 页</template>
              <template v-else>连续排版（ MinerU 不分页）</template>
              / {{ mdResult.total_chunks }} 个切块
            </n-text>
          </n-space>

          <n-skeleton v-if="mdLoading" text :repeat="3" />
          <n-empty v-else-if="!mdResult" description="选择文档后加载，MD 将按页展示并标记每页内的切块" style="padding: 24px 0" />
          <n-empty v-else-if="!mdResult.available" :description="mdResult.reason || '无法按页展示'" style="padding: 24px 0" />

          <div v-else v-for="pg in mdResult.pages" :key="pg.page" class="md-page">
            <div class="md-page-title">
              <n-text strong>{{ mdResult.paginated ? `第 ${pg.page} 页` : '整篇（不分页）' }}</n-text>
              <n-text depth="3" style="font-size: 12px">{{ markedCount(pg) }} 个切块</n-text>
            </div>
            <template v-for="(seg, i) in pg.segments" :key="i">
              <div v-if="seg.marked" class="seg seg-marked">
                <div class="seg-head">
                  <n-tag size="tiny" type="success" :bordered="false">{{ seg.chunk_type }}</n-tag>
                  <n-tag size="tiny" type="info" :bordered="false">chunk {{ seg.chunk_id }}</n-tag>
                  <n-text v-if="seg.page && mdResult.paginated" depth="3" style="font-size: 12px">p.{{ seg.page }}</n-text>
                  <n-tag v-else-if="seg.page" size="tiny" type="warning" :bordered="false">不分页</n-tag>
                  <n-text v-if="seg.img_path" depth="3" style="font-size: 12px">{{ seg.img_path }}</n-text>
                  <n-image
                    v-if="seg.img_path" :width="64" :height="64" object-fit="cover" class="seg-thumb" preview-disabled
                    :src="imgUrl(seg.img_path)"
                  />
                  <div style="flex:1"></div>
                  <n-button size="tiny" quaternary type="error" :loading="mdActionBusy.has(`${pg.page}:${seg.bidx}`)"
                    @click="mdviewAction('remove', pg, seg)">移除</n-button>
                </div>
                <div class="seg-text">{{ seg.text }}</div>
              </div>
              <div v-else class="seg seg-plain">
                <div class="seg-head">
                  <n-tag size="tiny" type="default" :bordered="false">{{ seg.chunk_type || 'block' }}</n-tag>
                  <n-tag v-if="seg.reason" size="tiny" type="warning" :bordered="false">{{ seg.reason }}</n-tag>
                  <div style="flex:1"></div>
                  <n-button v-if="canEmbed(seg)" size="tiny" quaternary type="primary" :loading="mdActionBusy.has(`${pg.page}:${seg.bidx}`)"
                    @click="mdviewAction('embed', pg, seg)">嵌入</n-button>
                </div>
                <div class="seg-text dim">{{ seg.text }}</div>
              </div>
            </template>
          </div>
        </n-card>
      </n-tab-pane>
    </n-tabs>

    <!-- 父块原文弹窗 -->
    <n-modal v-model:show="showParentModal" preset="card" title="父块原文（未切分的整段）" style="width: 720px">
      <n-spin :show="parentLoading">
        <div class="parent-text">{{ parentText }}</div>
      </n-spin>
    </n-modal>

    <!-- 图片预览弹窗 -->
    <n-modal v-model:show="showImgModal" preset="card" title="图片预览" style="width: 720px">
      <div style="display: flex; justify-content: center; overflow: hidden">
        <n-image
          v-if="imgPreviewSrc"
          :src="imgPreviewSrc"
          object-fit="contain"
          :preview-src="imgPreviewSrc"
          width="100%"
          style="max-width: 100%; max-height: 70vh"
        />
      </div>
    </n-modal>

    <!-- 文本详情弹窗 -->
    <n-modal v-model:show="showTextModal" preset="card" title="切块文本" style="width: 720px">
      <div class="parent-text">{{ detailText }}</div>
    </n-modal>
  </div>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NTabs, NTabPane, NCard, NIcon,
  NDataTable, NEmpty, NSpace, NInput, NSelect, NButton,
  NPagination, NProgress, NText, NH2, NUpload, NTag, NPopconfirm, useMessage,
  NSkeleton, NImage, NModal, NSpin,
} from 'naive-ui'
import { TrashOutline } from '@vicons/ionicons5'
import { useAdminStore } from '@/stores/admin'
import { useUserStore } from '@/stores/user'

const store = useAdminStore()
const userStore = useUserStore()
const message = useMessage()
const tab = ref('system')

// ── 切块类型（供筛选下拉，来自向量统计） ──
async function refreshChunkTypes() {
  try { await store.fetchDbStats() } catch (e) { /* 忽略 */ }
}

// ── MD 切块视图（md 按页展示 + 每页分块标记） ──
const mdSource = ref(null)
const mdResult = ref(null)
const mdLoading = ref(false)
const mdDocOptions = computed(() =>
  (store.systemDocs || []).map(d => ({ label: d.name, value: d.name }))
)
const markedCount = (pg) => (pg.segments || []).filter(s => s.marked).length
const imgUrl = (imgPath) =>
  `/api/documents/image/${encodeURIComponent(mdResult.value?.stem || '')}/${imgPath}?token=${encodeURIComponent(userStore.accessToken)}`

async function loadMdView() {
  if (!mdSource.value) return
  mdLoading.value = true
  try {
    mdResult.value = await store.fetchDbMdView(mdSource.value)
  } catch (e) {
    message.error(e.message)
    mdResult.value = null
  } finally {
    mdLoading.value = false
  }
}

// ── 文档视图手动调整：未嵌入块→嵌入向量库；已嵌入块→移除 ──
const mdActionBusy = ref(new Set())
const canEmbed = (seg) => seg && seg.bidx !== undefined
  && !['表格不录入向量库', '页眉/页脚等', '未成块'].includes(seg.reason)
  && !String(seg.img_path || '').toLowerCase().endsWith('.svg')
async function mdviewAction(action, pg, seg) {
  if (!seg || seg.bidx === undefined) return
  const key = `${pg.page}:${seg.bidx}`
  if (mdActionBusy.value.has(key)) return
  mdActionBusy.value = new Set(mdActionBusy.value).add(key)
  try {
    const payload = { source: mdSource.value, page: seg.page || pg.page, block_idx: seg.bidx }
    const res = action === 'embed' ? await store.mdviewEmbed(payload) : await store.mdviewRemove(payload)
    message.success((res && res.message) || (action === 'embed' ? '已嵌入' : '已移除'))
    await loadMdView()
    refreshChunkTypes()
    loadSystemDocs()
  } catch (e) {
    message.error(e?.message || '操作失败')
  } finally {
    const s = new Set(mdActionBusy.value); s.delete(key); mdActionBusy.value = s
  }
}
function jumpToMdView(source) {
  mdSource.value = source
  tab.value = 'mdview'
  loadMdView()
}

// ── 切块 ──
const chunkQuery = ref('')
const chunkType = ref(null)
const chunkPage = ref(1)
const chunkPageSize = ref(20)
const pageSizes = [10, 20, 50, 100, 200]
const chunkTypeOptions = computed(() => (store.dbStats?.chunk_types || []).map(t => ({ label: t, value: t })))

async function loadChunks() {
  try {
    await store.fetchDbChunks({
      page: chunkPage.value,
      page_size: chunkPageSize.value,
      query_text: chunkQuery.value || undefined,
      chunk_type: chunkType.value || undefined,
    })
  } catch (e) { message.error(e.message) }
}
function searchChunks() { chunkPage.value = 1; loadChunks() }
function changeChunkSize(size) { chunkPageSize.value = size; chunkPage.value = 1; loadChunks() }
const chunkColumns = [
  { title: '类型', key: 'chunk_type', width: 90 },
  { title: '来源', key: 'source', width: 180, ellipsis: { tooltip: true }, render: (row) => h('a', { style: 'cursor:pointer; color:var(--primary-color)', onClick: () => jumpToMdView(row.source) }, row.source) },
  { title: '页', key: 'page', width: 60 },
  { title: '文本', key: 'text', ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 200,
    render: (row) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, type: 'info', onClick: () => openDetail(row) }, { default: () => '详情' }),
        h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => jumpToMdView(row.source) }, { default: () => '视图' }),
        h(NPopconfirm,
          { onPositiveClick: () => removeDoc(row.source) },
          {
            trigger: () => h(NButton, {
              size: 'tiny', quaternary: true, type: 'error',
              loading: deletingSources.value.has(row.source),
              disabled: deletingSources.value.has(row.source),
            }, { icon: () => h(NIcon, { component: TrashOutline }) }),
            default: () => `删除来源 ${row.source} 的全部切块？`,
          }),
      ],
    }),
  },
]

// ── 查看父块（文本子块：按 parent_id 从数据库取父块整段原文） ──
const showParentModal = ref(false)
const parentText = ref('')
const parentLoading = ref(false)
const hasParent = (row) => row.chunk_type === 'text' && !!row.parent_id
async function openParent(row) {
  if (!hasParent(row)) return
  parentText.value = ''
  showParentModal.value = true
  parentLoading.value = true
  try {
    const data = await store.fetchChunkParent(row.parent_id)
    parentText.value = (data && data.text) || '(父块内容缺失)'
  } catch (e) {
    parentText.value = `(获取父块失败：${e.message})`
  } finally {
    parentLoading.value = false
  }
}

// ── 切块详情（图片→预览图片；文本→父块原文；无父块→显示整段文本） ──
const showImgModal = ref(false)
const imgPreviewSrc = ref('')
const showTextModal = ref(false)
const detailText = ref('')
const chunkImgUrl = (row) => {
  const stem = (row.source || '').replace(/\.[^.]+$/, '')
  return `/api/documents/image/${encodeURIComponent(stem)}/${row.img_path}?token=${encodeURIComponent(userStore.accessToken)}`
}
function openDetail(row) {
  if ((row.chunk_type === 'image' || row.chunk_type === 'chart') && row.img_path) {
    imgPreviewSrc.value = chunkImgUrl(row)
    showImgModal.value = true
    return
  }
  if (hasParent(row)) {
    openParent(row)
    return
  }
  detailText.value = row.text_full || row.text || '(无内容)'
  showTextModal.value = true
}

// ── 系统文档 ──
const systemPage = ref(1)
const systemPageSize = ref(20)
const deletingSources = ref(new Set())
async function loadSystemDocs() {
  try {
    await store.fetchSystemDocs({ page: systemPage.value, page_size: systemPageSize.value })
  } catch (e) { message.error(e.message) }
}
function changeSystemSize(size) { systemPageSize.value = size; systemPage.value = 1; loadSystemDocs() }

// ── 上传队列：MinIO 原始文件（文件维，独立分页） ──
const rawPage = ref(1)
const rawPageSize = ref(20)
const rawLoaded = ref(false)   // 首次加载完成后置 true：面板不再随异步数据消失/闪没
async function loadRawFiles() {
  try {
    await store.fetchSystemFiles({ page: rawPage.value, page_size: rawPageSize.value })
    rawLoaded.value = true
  } catch (e) { message.error(e.message) }
}
function changeRawSize(size) { rawPageSize.value = size; rawPage.value = 1; loadRawFiles() }

// ── 上传任务面板（临时态：仅进行中叠加，完成后自动收敛回纯 MinIO 队列） ──
const uploadTask = ref(null)
let timer = null

const isUploading = computed(() => uploadTask.value?.status === 'processing')
const taskTagType = computed(() => (uploadTask.value?.status === 'processing' ? 'info' : 'success'))
const uploadPercent = computed(() => {
  const t = uploadTask.value
  if (!t || !t.total) return 0
  return Math.round(((t.success || 0) + (t.fail || 0)) / t.total * 100)
})
// 合并表数据：仅以 MinIO 原始文件（文件维）为准（已入库/未入库）；
// 仅在"上传进行中"临时叠加任务文件与状态，完成后自动收敛，保证刷新前后一致
const queueRows = computed(() => {
  if (uploadTask.value?.status === 'processing') {
    const taskFiles = uploadTask.value?.files || {}
    const map = {}
    for (const f of store.systemFiles || []) map[f.name] = { name: f.name, imported: !!f.imported }
    for (const name of Object.keys(taskFiles)) {
      if (!map[name]) map[name] = { name, imported: false }
    }
    return Object.keys(map).map(name => ({
      name,
      state: taskFiles[name] || (map[name].imported ? 'imported' : 'not_imported'),
    }))
  }
  return (store.systemFiles || []).map(f => ({
    name: f.name,
    state: f.imported ? 'imported' : 'not_imported',
  }))
})

const _TASK_STATE = {
  pending: { type: 'info', text: '等待' },
  processing: { type: 'warning', text: '解析中' },
  success: { type: 'success', text: '成功' },
  failed: { type: 'error', text: '失败' },
  imported: { type: 'success', text: '已入库' },
  not_imported: { type: 'default', text: '未入库' },
}
const queueColumns = [
  { title: '文件名', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'state', width: 110,
    render: (r) => {
      const s = _TASK_STATE[r.state] || { type: 'default', text: r.state }
      return h(NTag, { type: s.type, size: 'small', bordered: false }, { default: () => s.text })
    },
  },
  {
    title: '操作', key: 'actions', width: 90,
    render: (row) => h(NPopconfirm,
      { onPositiveClick: () => removeRawFile(row.name) },
      {
        trigger: () => h(NButton, {
          size: 'tiny', quaternary: true, type: 'error',
          loading: deletingSources.value.has(row.name),
          disabled: deletingSources.value.has(row.name) || row.state === 'processing' || row.state === 'pending',
        }, { icon: () => h(NIcon, { component: TrashOutline }) }),
        default: () => `仅删除原始文件 ${row.name}？（向量/切块保留）`,
      }),
  },
]

function stopPolling() { if (timer) { clearInterval(timer); timer = null } }

function startPolling(taskId) {
  stopPolling()
  timer = setInterval(async () => {
    try {
      const t = await store.fetchUploadTask(taskId)
      uploadTask.value = t
      if (t.status !== 'processing') {
        stopPolling()
        loadSystemDocs(); loadRawFiles(); refreshChunkTypes()
        // 收敛：任务结束即回到纯 MinIO 队列视图，与刷新后一致；结果用 toast 汇总
        const ok = t.success || 0
        const bad = t.fail || 0
        if (bad > 0) {
          message.warning(`上传完成：成功 ${ok} / 失败 ${bad}（失败文件未在队列中，可重新选择上传）`)
        } else {
          message.success(`上传完成：成功 ${ok} 个文件`)
        }
        uploadTask.value = null
      }
    } catch { /* ignore */ }
  }, 1500)
}

async function submitFiles(files) {
  if (!files.length) return
  try {
    const res = await store.uploadSystemDocs(files)
    const names = res.files || []
    // 先本地秒开任务面板，轮询拿到真实逐文件状态
    uploadTask.value = {
      id: res.task_id, status: 'processing', total: names.length,
      success: 0, fail: 0, failures: [],
      files: Object.fromEntries(names.map(n => [n, 'pending'])),
      started_at: new Date().toISOString(), finished_at: null,
    }
    startPolling(res.task_id)
  } catch (e) { message.error(e.message) }
}

function doUpload({ fileList }) {
  const files = fileList.map(f => f.file).filter(Boolean)
  submitFiles(files)
}
const systemColumns = [
  { title: '文件名', key: 'name', ellipsis: { tooltip: true }, render: (row) => h('a', { style: 'cursor:pointer; color:var(--primary-color)', onClick: () => jumpToMdView(row.name) }, row.name) },
  { title: '切块数', key: 'chunks', width: 100 },
  {
    title: '操作', key: 'actions', width: 150,
    render: (row) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => jumpToMdView(row.name) }, { default: () => '视图' }),
        h(NPopconfirm,
          { onPositiveClick: () => removeDoc(row.name) },
          {
            trigger: () => h(NButton, {
              size: 'tiny', quaternary: true, type: 'error',
              loading: deletingSources.value.has(row.name),
              disabled: deletingSources.value.has(row.name),
            }, { icon: () => h(NIcon, { component: TrashOutline }) }),
            default: () => `删除 ${row.name}？`,
          }),
      ],
    }),
  },
]

async function removeDoc(source) {
  if (deletingSources.value.has(source)) return
  deletingSources.value.add(source)
  try {
    await store.deleteDocument(source)
    message.success('已删除')
    loadChunks(); loadSystemDocs(); loadRawFiles(); refreshChunkTypes()
  } catch (e) { message.error(e.message) }
  finally { deletingSources.value.delete(source) }
}

async function removeRawFile(source) {
  if (deletingSources.value.has(source)) return
  deletingSources.value.add(source)
  try {
    await store.deleteSystemRawFile(source)
    message.success('已删除原始文件')
    loadRawFiles()
  } catch (e) { message.error(e.message) }
  finally { deletingSources.value.delete(source) }
}

function handleTab(name) {
  if (name === 'system') { loadSystemDocs(); loadRawFiles() }
}
watch(tab, (name) => handleTab(name))

onMounted(async () => {
  await Promise.all([
    refreshChunkTypes(),
    loadChunks(),
    loadSystemDocs(),
    loadRawFiles(),
  ])
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.md-page {
  margin-bottom: 18px;
  border: 1px dashed var(--divider-color, #dddddd);
  border-radius: 6px;
  padding: 10px 12px;
  background: transparent;
}
.md-page-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--divider-color, #eee);
  padding-bottom: 6px;
}
.seg {
  border-left: 3px solid #c8c8c8;
  padding: 6px 10px;
  margin: 6px 0;
  border-radius: 4px;
  background: transparent;
}
.seg-marked {
  border-left-color: #18a058;
  background: rgba(24, 160, 88, 0.07);
}
.seg-plain {
  border-left-color: #e0e0e0;
}
.seg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.seg-thumb {
  margin-left: auto;
}
.seg-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  max-height: 220px;
  overflow: auto;
}
.seg-text.dim {
  color: #909399;
  font-size: 12px;
}
.parent-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  max-height: 60vh;
  overflow: auto;
}
</style>
