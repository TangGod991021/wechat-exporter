<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { darkTheme, dateZhCN, zhCN, createDiscreteApi } from 'naive-ui'
import {
  AlbumsOutline,
  ChatbubblesOutline,
  CheckmarkCircle,
  ChevronBackOutline,
  ChevronForwardOutline,
  DownloadOutline,
  FolderOpenOutline,
  KeyOutline,
  MicOutline,
  MoonOutline,
  OpenOutline,
  RefreshOutline,
  SearchOutline,
  ServerOutline,
  SunnyOutline,
} from '@vicons/ionicons5'
import { api, waitJob } from './api'
import MessageContent from './components/MessageContent.vue'

const { message: msgLight } = createDiscreteApi(['message'])
const { message: msgDark } = createDiscreteApi(['message'], {
  configProviderProps: { theme: darkTheme },
})
const message = {
  success: (t: string) => (dark.value ? msgDark : msgLight).success(t),
  error: (t: string) => (dark.value ? msgDark : msgLight).error(t),
  warning: (t: string) => (dark.value ? msgDark : msgLight).warning(t),
}

const dark = ref(localStorage.getItem('theme') === 'dark')
const theme = computed(() => (dark.value ? darkTheme : null))
const overrides = {
  common: {
    primaryColor: '#07c160',
    primaryColorHover: '#36d27c',
    primaryColorPressed: '#06ad56',
    primaryColorSuppl: '#07c160',
    borderRadius: '10px',
  },
}

function toggleTheme(v: boolean) {
  dark.value = v
  localStorage.setItem('theme', v ? 'dark' : 'light')
  document.documentElement.classList.toggle('dark', v)
}

const step = ref(1)
const loading = ref(true)
const boot = ref<any>(null)
const accounts = computed<any[]>(() => boot.value?.accounts || [])
const selected = ref('')
const account = computed<any>(() => accounts.value.find((a) => a.folder === selected.value) || null)

const jobs = reactive<Record<string, any>>({
  keys: { progress: 0, status: '', message: '', logs: [] },
  core: { progress: 0, status: '', message: '', logs: [] },
  prepare: { progress: 0, status: '', message: '', logs: [] },
  export: { progress: 0, status: '', message: '', logs: [] },
})
const activeJob = ref('')
const busy = computed(() => Object.values(jobs).some((j: any) => j.status === 'running'))

async function loadBoot() {
  loading.value = true
  try {
    boot.value = await api.bootstrap()
    if (!selected.value && accounts.value.length) {
      const last = boot.value.last_account
      selected.value =
        accounts.value.find((a) => a.folder === last)?.folder || accounts.value[0].folder
    }
  } catch (e: any) {
    message.error('读取状态失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function resetSelection() {
  sessionsLoaded.value = false
  sessions.value = []
  picked.value = []
  preparedSig.value = ''
}

function selectAccount(a: any) {
  if (a.folder !== selected.value) resetSelection()
  selected.value = a.folder
  api.setConfig({ last_account: a.folder }).catch(() => {})
}

async function pickDir() {
  const r = await api.pickFolder()
  if (r.path) {
    await api.setConfig({ wechat_root: r.path })
    resetSelection()
    await loadBoot()
    message.success('数据目录已更新')
  }
}

async function runJob(kind: string, starter: () => Promise<any>) {
  jobs[kind] = { progress: 0, status: 'running', message: '启动中…', logs: [] }
  activeJob.value = kind
  try {
    const { job } = await starter()
    const done = await waitJob(job, (j) => {
      jobs[kind] = j
    })
    jobs[kind] = done
    await loadBoot()
    return done
  } catch (e: any) {
    jobs[kind] = { ...jobs[kind], status: 'error', message: e.message || String(e) }
    message.error(e.message || '任务失败')
    return null
  }
}

function doKeys() {
  return runJob('keys', () => api.startKeys(account.value.folder))
}

function runKeysStep() {
  if (!account.value) return null
  // 已提取过密钥时只需补建会话索引，不必再次读取微信内存
  if (account.value.has_keys) {
    return runJob('core', () => api.startCore(account.value.folder))
  }
  return doKeys()
}

async function ensureCore() {
  if (!account.value) return null
  if (account.value.messages_ready) return true
  const done = await runJob('core', () => api.startCore(account.value.folder))
  if (done) sessionsLoaded.value = false
  return done
}

const preparedSig = ref('')
const pickedSig = computed(() => picked.value.slice().sort().join('|'))
const prepared = computed(
  () => picked.value.length > 0 && preparedSig.value === pickedSig.value,
)

function doPrepare() {
  if (!account.value || !picked.value.length) return null
  const sig = pickedSig.value
  return runJob('prepare', () =>
    api.prepare(account.value.folder, picked.value),
  ).then((done) => {
    if (done) preparedSig.value = sig
    return done
  })
}

/* ---------- 会话 ---------- */
const sessions = ref<any[]>([])
const sessionsLoaded = ref(false)
const sessionLoading = ref(false)
const search = ref('')
const filter = ref<'all' | 'group' | 'single'>('all')
const picked = ref<string[]>([])

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return sessions.value.filter((s) => {
    if (filter.value === 'group' && !s.is_group) return false
    if (filter.value === 'single' && s.is_group) return false
    if (!q) return true
    return s.name.toLowerCase().includes(q) || s.username.toLowerCase().includes(q)
  })
})

async function loadSessions() {
  if (!account.value || sessionsLoaded.value) return
  sessionLoading.value = true
  try {
    const r = await api.sessions(account.value.folder)
    sessions.value = r.sessions
    sessionsLoaded.value = true
  } catch (e: any) {
    message.error('读取会话失败：' + e.message)
  } finally {
    sessionLoading.value = false
  }
}

function togglePick(u: string) {
  const i = picked.value.indexOf(u)
  if (i >= 0) picked.value.splice(i, 1)
  else picked.value.push(u)
}

const allFilteredPicked = computed(
  () => filtered.value.length > 0 && filtered.value.every((s) => picked.value.includes(s.username)),
)

function toggleAllFiltered() {
  if (allFilteredPicked.value) {
    const set = new Set(filtered.value.map((s) => s.username))
    picked.value = picked.value.filter((u) => !set.has(u))
  } else {
    const set = new Set(picked.value)
    filtered.value.forEach((s) => set.add(s.username))
    picked.value = Array.from(set)
  }
}

/* ---------- 聊天预览 ---------- */
const previewShow = ref(false)
const previewSession = ref<any>(null)
const messages = ref<any[]>([])
const previewLoading = ref(false)

async function preview(s: any) {
  previewSession.value = s
  messages.value = []
  previewShow.value = true
  await loadMore()
}

async function loadMore() {
  if (!account.value || !previewSession.value) return
  previewLoading.value = true
  try {
    const before = messages.value.length ? messages.value[0].ts : undefined
    const r = await api.chat(account.value.folder, previewSession.value.username, 100, before)
    messages.value = [...r.messages, ...messages.value]
  } catch (e: any) {
    message.error('加载消息失败：' + e.message)
  } finally {
    previewLoading.value = false
  }
}

function isSystem(m: any) {
  return m.sender === '系统' || ['system', 'pat', 'unsupported'].includes(m.kind)
}

function fileUrl(p: string) {
  return '/api/file?path=' + encodeURIComponent(p)
}

/* ---------- 转发聊天记录 ---------- */
const recordShow = ref(false)
const recordData = ref<any>(null)

function openRecord(content: any) {
  recordData.value = content
  recordShow.value = true
}

/* ---------- 导出 ---------- */
const formats = ref<string[]>(['html'])
const range = ref<[number, number] | null>(null)
const exported = ref<any>(null)
const exportMode = ref<'archive' | 'link'>('archive')

async function doExport() {
  if (!picked.value.length) {
    message.warning('请先选择要导出的会话')
    return
  }
  if (!formats.value.length) {
    message.warning('请至少选择一种格式')
    return
  }
  const toDate = (ms: number) => {
    const d = new Date(ms)
    const p = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  }
  exported.value = null
  const done = await runJob('export', () =>
    api.startExport({
      account: account.value.folder,
      targets: picked.value,
      formats: formats.value,
      since: range.value ? toDate(range.value[0]) : null,
      until: range.value ? toDate(range.value[1]) : null,
      archive: exportMode.value === 'archive',
    }),
  )
  if (done?.result) exported.value = done.result
}

/* ---------- 工具 ---------- */
function initial(name: string) {
  return (name || '?').trim().slice(0, 1).toUpperCase()
}
function fmtSize(mb: number) {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return (mb || 0).toFixed(1) + ' MB'
}
function fmtDate(ts: number) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString('zh-CN')
}
function canNext() {
  if (step.value === 1) return !!selected.value
  if (step.value === 2) return !!account.value?.has_keys && !!account.value?.core_ready
  if (step.value === 3) return picked.value.length > 0
  if (step.value === 4) return prepared.value
  return false
}

async function next() {
  if (step.value === 2) {
    if (!account.value?.messages_ready) {
      const ok = await ensureCore()
      if (!ok) return
    }
    if (!sessionsLoaded.value) await loadSessions()
  }
  step.value = Math.min(5, step.value + 1)
}

function back() {
  step.value = Math.max(1, step.value - 1)
}

const stepDefs = [
  { title: '选择账号', desc: '本机微信账号' },
  { title: '提取密钥', desc: '读取微信进程密钥' },
  { title: '选择会话', desc: '群聊或联系人' },
  { title: '准备数据', desc: '按所选会话解密' },
  { title: '导出', desc: '格式与时间范围' },
]

function goStep(n: number) {
  if (n < step.value) step.value = n
}

onMounted(() => {
  document.documentElement.classList.toggle('dark', dark.value)
  loadBoot()
})
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="overrides" :locale="zhCN" :date-locale="dateZhCN">
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="logo" aria-hidden="true">
            <svg viewBox="0 0 64 64" width="100%" height="100%">
              <defs>
                <linearGradient id="logoGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stop-color="#30d684" />
                  <stop offset="1" stop-color="#049a4c" />
                </linearGradient>
              </defs>
              <rect width="64" height="64" rx="14" fill="url(#logoGradient)" />
              <path
                d="M22 13h20a10 10 0 0 1 10 10v10a10 10 0 0 1-10 10H27l-8 8V43h3a10 10 0 0 1-10-10V23a10 10 0 0 1 10-10Z"
                fill="#fff"
              />
              <rect x="28" y="18" width="8" height="13" rx="2" fill="#07b25f" />
              <path d="M22 28h20L32 41 22 28Z" fill="#07b25f" />
            </svg>
          </div>
          <div>
            <div class="title">微信聊天记录导出</div>
            <div class="sub">本地处理 · 不上传 · v{{ boot?.version || '0.1.0' }}</div>
          </div>
        </div>
        <div class="right">
          <span class="status" :class="{ on: boot?.weixin_running }">
            <i></i>{{ boot?.weixin_running ? '微信运行中' : '微信未运行' }}
          </span>
          <n-tag v-if="boot?.wechat_version" size="small" round>
            微信 {{ boot.wechat_version }}
          </n-tag>
          <n-switch :value="dark" size="small" @update:value="toggleTheme">
            <template #checked><n-icon><MoonOutline /></n-icon></template>
            <template #unchecked><n-icon><SunnyOutline /></n-icon></template>
          </n-switch>
        </div>
      </header>

      <main class="main">
        <n-card class="steps-card" :bordered="false">
          <div class="steps">
            <template v-for="(s, i) in stepDefs" :key="s.title">
              <div
                class="step"
                :class="{
                  active: step === i + 1,
                  done: step > i + 1,
                  clickable: i + 1 < step,
                }"
                :title="i + 1 < step ? '返回这一步' : ''"
                @click="goStep(i + 1)"
              >
                <div class="step-dot">
                  <n-icon v-if="step > i + 1"><CheckmarkCircle /></n-icon>
                  <span v-else>{{ i + 1 }}</span>
                </div>
                <div class="step-text">
                  <div class="step-title">{{ s.title }}</div>
                  <div class="step-desc">{{ s.desc }}</div>
                </div>
              </div>
              <div
                v-if="i < stepDefs.length - 1"
                class="step-line"
                :class="{ done: step > i + 1 }"
              />
            </template>
          </div>
        </n-card>

        <transition name="fade" mode="out-in">
          <!-- ① 账号 -->
          <section v-if="step === 1" key="1" class="panel">
            <div class="panel-head">
              <div>
                <h2>选择要导出的微信账号</h2>
                <p class="hint">数据目录：{{ boot?.wechat_root || '未找到，请手动选择' }}</p>
              </div>
              <div class="actions">
                <n-button quaternary :disabled="busy" @click="pickDir">
                  <template #icon><n-icon><FolderOpenOutline /></n-icon></template>
                  选择数据目录
                </n-button>
                <n-button quaternary :disabled="busy" @click="loadBoot">
                  <template #icon><n-icon><RefreshOutline /></n-icon></template>
                  重新扫描
                </n-button>
              </div>
            </div>

            <n-spin :show="loading">
              <div v-if="accounts.length" class="accounts">
                <div
                  v-for="a in accounts"
                  :key="a.folder"
                  class="acct"
                  :class="{ active: selected === a.folder }"
                  @click="selectAccount(a)"
                >
                  <div class="avatar">{{ initial(a.nickname) }}</div>
                  <div class="acct-info">
                    <div class="acct-name">
                      {{ a.nickname }}
                      <n-tag v-if="a.decrypted" type="success" size="tiny" round>已解密</n-tag>
                      <n-tag v-else-if="a.has_keys" size="tiny" round>已取密钥</n-tag>
                    </div>
                    <div class="acct-wxid">{{ a.username }}</div>
                    <div class="acct-meta">
                      {{ fmtSize(a.size_mb) }} · {{ a.db_count }} 个库 · 最近 {{ fmtDate(a.last_active) }}
                    </div>
                  </div>
                  <n-icon v-if="selected === a.folder" class="check" size="22" color="#07c160">
                    <CheckmarkCircle />
                  </n-icon>
                </div>
              </div>
              <n-empty
                v-else
                description="未找到微信 4.x 账号数据"
                style="padding: 60px 0"
              >
                <template #extra>
                  <div class="hint" style="margin-bottom: 12px">
                    请确认微信已登录，或手动选择 xwechat_files 所在目录
                  </div>
                  <n-button type="primary" @click="pickDir">选择数据目录</n-button>
                </template>
              </n-empty>
            </n-spin>
          </section>

          <!-- ② 密钥 -->
          <section v-else-if="step === 2" key="2" class="panel">
            <div class="panel-head">
              <div>
                <h2>提取密钥</h2>
                <p class="hint">请保持微信登录状态，密钥只存在于运行中的微信进程内存里</p>
              </div>
              <div class="actions">
                <n-button type="primary" :loading="busy" :disabled="busy" @click="runKeysStep">
                  {{ account?.has_keys ? '建立会话索引' : '提取密钥' }}
                </n-button>
              </div>
            </div>

            <div class="prepare-grid">
              <div class="prep">
                <div class="prep-icon"><n-icon size="22"><KeyOutline /></n-icon></div>
                <div class="prep-title">数据库密钥</div>
                <div class="prep-desc">从微信进程提取 SQLCipher 密钥；后续步骤可离线执行</div>
                <n-tag :type="account?.has_keys ? 'success' : 'default'" size="small" round>
                  {{ account?.has_keys ? '已完成' : '未开始' }}
                </n-tag>
              </div>
              <div class="prep">
                <div class="prep-icon"><n-icon size="22"><ServerOutline /></n-icon></div>
                <div class="prep-title">会话索引</div>
                <div class="prep-desc">解密 session.db / contact.db，用于下一步加载会话列表</div>
                <n-tag :type="account?.core_ready ? 'success' : 'default'" size="small" round>
                  {{ account?.core_ready ? '已完成' : '未开始' }}
                </n-tag>
              </div>
            </div>

            <div v-if="activeJob && jobs[activeJob]?.status" class="console">
              <div class="console-head">
                <span>{{ jobs[activeJob].status === 'running' ? '进行中' : jobs[activeJob].status === 'done' ? '已完成' : '失败' }}</span>
                <span>{{ jobs[activeJob].message }}</span>
                <span v-if="jobs[activeJob].progress" class="pct">{{ jobs[activeJob].progress }}%</span>
              </div>
              <div class="console-body">
                <div v-for="(l, i) in jobs[activeJob].logs.slice(-6)" :key="i">{{ l }}</div>
              </div>
            </div>

            <n-alert v-if="!boot?.weixin_running" type="warning" style="margin-top: 16px">
              当前没有检测到运行中的微信。密钥提取需要微信已登录。
            </n-alert>
          </section>

          <!-- ③ 会话 -->
          <section v-else-if="step === 3" key="3" class="panel">
            <div class="panel-head">
              <div>
                <h2>选择会话</h2>
                <p class="hint">
                  已选 {{ picked.length }} 个 · 共 {{ sessions.length }} 个会话
                </p>
              </div>
              <div class="actions">
                <n-input
                  v-model:value="search"
                  placeholder="搜索群名或联系人"
                  clearable
                  style="width: 240px"
                >
                  <template #prefix><n-icon><SearchOutline /></n-icon></template>
                </n-input>
                <n-button-group size="small">
                  <n-button :type="filter === 'all' ? 'primary' : 'default'" @click="filter = 'all'">全部</n-button>
                  <n-button :type="filter === 'group' ? 'primary' : 'default'" @click="filter = 'group'">群聊</n-button>
                  <n-button :type="filter === 'single' ? 'primary' : 'default'" @click="filter = 'single'">私聊</n-button>
                </n-button-group>
              </div>
            </div>

            <div class="sess-toolbar">
              <n-checkbox :checked="allFilteredPicked" @update:checked="toggleAllFiltered">
                全选当前列表
              </n-checkbox>
              <span class="hint">{{ filtered.length }} 个结果</span>
            </div>

            <n-spin :show="sessionLoading">
              <div class="sessions">
                <div
                  v-for="s in filtered"
                  :key="s.username"
                  class="sess"
                  :class="{ picked: picked.includes(s.username) }"
                >
                  <n-checkbox
                    :checked="picked.includes(s.username)"
                    @update:checked="togglePick(s.username)"
                  />
                  <div class="avatar sm" @click="preview(s)">{{ initial(s.name) }}</div>
                  <div class="sess-main" @click="preview(s)">
                    <div class="sess-name">
                      {{ s.name }}
                      <n-tag v-if="s.is_group" size="tiny" round>群</n-tag>
                    </div>
                    <div class="sess-summary">{{ s.summary || '（无摘要）' }}</div>
                  </div>
                  <div class="sess-side">
                    <div class="count">{{ s.count }} 条</div>
                    <div class="time">{{ s.last_time_text }}</div>
                  </div>
                </div>
                <n-empty v-if="!filtered.length && !sessionLoading" description="没有匹配的会话" style="padding: 50px 0" />
              </div>
            </n-spin>
          </section>

          <!-- ④ 准备所选数据 -->
          <section v-else-if="step === 4" key="4" class="panel">
            <div class="panel-head">
              <div>
                <h2>准备所选数据</h2>
                <p class="hint">已选 {{ picked.length }} 个会话 · 仅解密这些会话实际引用的图片 / 语音 / 视频</p>
              </div>
              <div class="actions">
                <n-tag v-if="prepared" type="success" size="small" round>已准备</n-tag>
                <n-button
                  type="primary"
                  :loading="jobs.prepare.status === 'running'"
                  :disabled="busy && jobs.prepare.status !== 'running'"
                  @click="doPrepare"
                >
                  开始准备
                </n-button>
              </div>
            </div>

            <div class="prepare-grid">
              <div class="prep">
                <div class="prep-icon"><n-icon size="22"><ChatbubblesOutline /></n-icon></div>
                <div class="prep-title">消息数据库</div>
                <div class="prep-desc">message_0 / media_0（第 3 步已加载，准备前会自动刷新）</div>
                <n-tag :type="account?.messages_ready ? 'success' : 'default'" size="small" round>
                  {{ account?.messages_ready ? '已完成' : '未开始' }}
                </n-tag>
              </div>
              <div class="prep">
                <div class="prep-icon"><n-icon size="22"><AlbumsOutline /></n-icon></div>
                <div class="prep-title">图片 / 视频</div>
                <div class="prep-desc">只解密所选会话命中的图片，并转码其中的 HEVC 视频</div>
                <n-tag :type="prepared ? 'success' : 'default'" size="small" round>
                  {{ prepared ? '已完成' : '待准备' }}
                </n-tag>
              </div>
              <div class="prep">
                <div class="prep-icon"><n-icon size="22"><MicOutline /></n-icon></div>
                <div class="prep-title">语音</div>
                <div class="prep-desc">只转换所选会话命中的 SILK 语音</div>
                <n-tag :type="prepared ? 'success' : 'default'" size="small" round>
                  {{ prepared ? '已完成' : '待准备' }}
                </n-tag>
              </div>
            </div>

            <div v-if="jobs.prepare.status" style="margin-top: 16px">
              <n-progress type="line" :percentage="jobs.prepare.progress || 0" :show-indicator="false" />
              <p class="hint" style="margin-top: 6px">{{ jobs.prepare.message }}</p>
            </div>

            <div v-if="activeJob && jobs[activeJob]?.status" class="console">
              <div class="console-head">
                <span>{{ jobs[activeJob].status === 'running' ? '进行中' : jobs[activeJob].status === 'done' ? '已完成' : '失败' }}</span>
                <span>{{ jobs[activeJob].message }}</span>
                <span v-if="jobs[activeJob].progress" class="pct">{{ jobs[activeJob].progress }}%</span>
              </div>
              <div class="console-body">
                <div v-for="(l, i) in jobs[activeJob].logs.slice(-6)" :key="i">{{ l }}</div>
              </div>
            </div>

            <n-alert v-if="prepared" type="success" style="margin-top: 16px">
              所选会话的数据已准备完成，可以进入导出。
            </n-alert>
          </section>

          <!-- ⑤ 导出 -->
          <section v-else key="5" class="panel">
            <div class="panel-head">
              <div>
                <h2>导出</h2>
                <p class="hint">已选 {{ picked.length }} 个会话 · 数据已准备完成</p>
              </div>
            </div>

            <div class="export-grid">
              <n-card title="导出格式" :bordered="false" class="soft-card">
                <n-checkbox-group v-model:value="formats">
                  <div class="fmt-list">
                    <n-checkbox value="html">HTML（气泡样式，含图片语音）</n-checkbox>
                    <n-checkbox value="txt">TXT（纯文本）</n-checkbox>
                    <n-checkbox value="json">JSON（结构化）</n-checkbox>
                    <n-checkbox value="csv">CSV（Excel 可打开）</n-checkbox>
                  </div>
                </n-checkbox-group>
              </n-card>

              <n-card title="时间范围" :bordered="false" class="soft-card">
                <n-date-picker
                  v-model:value="range"
                  type="daterange"
                  clearable
                  style="width: 100%"
                  start-placeholder="开始日期"
                  end-placeholder="结束日期"
                />
                <p class="hint" style="margin-top: 10px">留空表示导出全部历史消息</p>
              </n-card>

              <n-card title="输出位置" :bordered="false" class="soft-card">
                <div class="path-text">{{ boot?.export_dir }}</div>
                <n-button size="small" quaternary style="margin-top: 10px" @click="api.openFolder(boot?.export_dir)">
                  <template #icon><n-icon><OpenOutline /></n-icon></template>
                  打开文件夹
                </n-button>
              </n-card>

              <n-card title="导出方式" :bordered="false" class="soft-card">
                <n-radio-group v-model:value="exportMode">
                  <div class="mode-list">
                    <n-radio value="archive">
                      <div class="mode-title">归档文件夹（推荐）</div>
                      <div class="mode-desc">
                        每个会话一个文件夹，图片/视频/语音自动复制，HTML 可离线打开
                      </div>
                    </n-radio>
                    <n-radio value="link">
                      <div class="mode-title">仅引用本机文件</div>
                      <div class="mode-desc">
                        导出快、不复制媒体；移动目录或换电脑后媒体失效
                      </div>
                    </n-radio>
                  </div>
                </n-radio-group>
              </n-card>
            </div>

            <div class="export-actions">
              <n-button
                type="primary"
                size="large"
                :loading="jobs.export.status === 'running'"
                :disabled="busy && jobs.export.status !== 'running'"
                @click="doExport"
              >
                <template #icon><n-icon><DownloadOutline /></n-icon></template>
                开始导出
              </n-button>
              <div v-if="jobs.export.status === 'running'" class="export-progress">
                <n-progress
                  type="line"
                  :percentage="jobs.export.progress"
                  :show-indicator="false"
                  style="width: 260px"
                />
                <span class="hint">{{ jobs.export.message }}</span>
              </div>
            </div>

            <n-card v-if="exported" title="导出完成" :bordered="false" class="soft-card" style="margin-top: 16px">
              <div class="files">
                <div v-for="f in exported.files" :key="f" class="file">
                  <n-icon><ChatbubblesOutline /></n-icon>
                  <span class="file-path">{{ f }}</span>
                  <n-button size="tiny" quaternary @click="api.openFolder(f)">打开</n-button>
                </div>
              </div>
              <n-button size="small" style="margin-top: 10px" @click="api.openFolder(exported.dir)">
                打开导出目录
              </n-button>
            </n-card>
          </section>
        </transition>

        <footer class="footer">
          <n-button v-if="step > 1" quaternary @click="back">
            <template #icon><n-icon><ChevronBackOutline /></n-icon></template>
            上一步
          </n-button>
          <span style="flex: 1" />
          <n-button v-if="step < 5" type="primary" :disabled="!canNext()" :loading="jobs.core.status === 'running'" @click="next">
            下一步
            <template #icon><n-icon><ChevronForwardOutline /></n-icon></template>
          </n-button>
        </footer>
      </main>

      <!-- 聊天预览 -->
      <n-modal
        v-model:show="previewShow"
        preset="card"
        style="width: 680px; max-width: 92vw"
        :title="previewSession?.name + ' · 消息预览'"
        :bordered="false"
      >
        <div class="chat-view">
          <div v-if="messages.length" style="text-align: center; margin-bottom: 8px">
            <n-button size="tiny" quaternary :loading="previewLoading" @click="loadMore">
              加载更早的消息
            </n-button>
          </div>
          <div
            v-for="m in messages"
            :key="m.local_id"
            class="msg"
            :class="{ me: m.sender === '我' }"
          >
            <template v-if="isSystem(m)">
              <div class="sys-line">{{ m.time }} {{ m.text }}</div>
            </template>
            <template v-else>
              <div class="meta">{{ m.sender }} · {{ m.time }}</div>
              <div class="bubble"><MessageContent :msg="m" @open-record="openRecord" /></div>
            </template>
          </div>
          <n-empty v-if="!messages.length && !previewLoading" description="没有消息" />
        </div>
      </n-modal>

      <!-- 转发聊天记录详情 -->
      <n-modal
        v-model:show="recordShow"
        preset="card"
        style="width: 600px; max-width: 94vw"
        :title="recordData?.title || '转发聊天记录'"
        :bordered="false"
      >
        <div class="record-view">
          <div
            v-for="(r, i) in recordData?.records || []"
            :key="i"
            class="record-row"
          >
            <div class="rr-head">
              <span class="rr-sender">{{ r.sender }}</span>
              <span class="rr-time">{{ r.time }}</span>
            </div>
            <div class="rr-text">{{ r.text }}</div>
            <div
              v-if="r.size || ((r.kind === 'image' || r.kind === 'video') && !r.media)"
              class="rr-meta"
            >
              <span v-if="r.size">{{ r.size }}</span>
              <span v-if="r.kind === 'image' && !r.media">原图未缓存到本地</span>
              <span v-if="r.kind === 'video' && !r.media">原视频未缓存到本地</span>
            </div>
            <video
              v-if="r.media && r.media.toLowerCase().endsWith('.mp4')"
              class="rr-img"
              controls
              :src="fileUrl(r.media)"
            />
            <audio
              v-else-if="r.media && r.media.toLowerCase().endsWith('.wav')"
              controls
              :src="fileUrl(r.media)"
            />
            <img v-else-if="r.media" class="rr-img" :src="fileUrl(r.media)" loading="lazy" />
          </div>
          <n-empty
            v-if="!(recordData?.records || []).length"
            description="该转发记录没有可解析的明细"
          />
        </div>
      </n-modal>
    </div>
  </n-config-provider>
</template>

<style scoped>
.app {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f5f6f8;
  color: #1f2329;
}
html.dark .app {
  background: #101014;
  color: #e8e8e8;
}

.topbar {
  height: 64px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}
html.dark .topbar {
  background: rgba(28, 28, 32, 0.8);
  border-bottom-color: rgba(255, 255, 255, 0.08);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: linear-gradient(135deg, #07c160, #10b981);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 6px 16px rgba(7, 193, 96, 0.28);
}
.title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.2;
}
.sub {
  font-size: 12px;
  opacity: 0.55;
}
.right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  opacity: 0.7;
}
.status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #d03050;
}
.status.on i {
  background: #18a058;
  box-shadow: 0 0 0 3px rgba(24, 160, 88, 0.15);
}

.main {
  flex: 1;
  overflow: auto;
  padding: 20px 24px 24px;
  max-width: 1160px;
  width: 100%;
  margin: 0 auto;
}

.steps-card {
  background: transparent;
  margin-bottom: 8px;
}
.steps-card :deep(.n-card__content) {
  padding: 6px 4px 14px;
}
.steps {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 2px;
}
.step {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}
.step.clickable {
  cursor: pointer;
}
.step-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1.5px solid rgba(127, 127, 127, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: #999;
  transition: all 0.18s ease;
  flex: none;
}
.step.active .step-dot {
  border-color: #07c160;
  background: #07c160;
  color: #fff;
}
.step.done .step-dot {
  border-color: #07c160;
  color: #07c160;
  background: rgba(7, 193, 96, 0.12);
}
.step.clickable:hover .step-dot {
  box-shadow: 0 0 0 4px rgba(7, 193, 96, 0.14);
}
.step-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
}
html.dark .step-title {
  color: #e8e8e8;
}
.step.active .step-title {
  color: #07a04c;
}
html.dark .step.active .step-title {
  color: #4ade80;
}
.step-desc {
  font-size: 12px;
  opacity: 0.5;
  white-space: nowrap;
}
.step-line {
  flex: 1;
  min-width: 30px;
  height: 1px;
  background: rgba(127, 127, 127, 0.25);
}
.step-line.done {
  background: #07c160;
}

.panel {
  padding: 4px 0 12px;
}
.panel-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin: 10px 0 16px;
}
.panel-head h2 {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 600;
}
.hint {
  margin: 0;
  font-size: 12px;
  opacity: 0.55;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.accounts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.acct {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border-radius: 14px;
  background: #fff;
  border: 1.5px solid transparent;
  cursor: pointer;
  transition: all 0.18s ease;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
}
html.dark .acct {
  background: #1c1c22;
}
.acct:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}
html.dark .acct:hover {
  background: #23232a;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.acct.active {
  border-color: #07c160;
  box-shadow: 0 8px 24px rgba(7, 193, 96, 0.16);
}
.avatar {
  width: 48px;
  height: 48px;
  flex: none;
  border-radius: 14px;
  background: linear-gradient(135deg, #e8f7ee, #d4f0e0);
  color: #07a04c;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 20px;
}
html.dark .avatar {
  background: #17301f;
  color: #4ade80;
}
.avatar.sm {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  font-size: 16px;
  cursor: pointer;
}
.acct-info {
  flex: 1;
  min-width: 0;
}
.acct-name {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.acct-wxid {
  font-size: 12px;
  opacity: 0.5;
  font-family: Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.acct-meta {
  font-size: 12px;
  opacity: 0.55;
  margin-top: 2px;
}
.check {
  flex: none;
}

.prepare-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}
.prep {
  background: #fff;
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
}
html.dark .prep {
  background: #1c1c22;
}
.prep-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(7, 193, 96, 0.1);
  color: #07a04c;
  display: flex;
  align-items: center;
  justify-content: center;
}
html.dark .prep-icon {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
}
.prep-title {
  font-weight: 600;
  margin-top: 4px;
}
.prep-desc {
  font-size: 12px;
  opacity: 0.55;
  min-height: 34px;
}
.prep :deep(.n-tag) {
  align-self: flex-start;
}

.console {
  margin-top: 16px;
  border-radius: 12px;
  overflow: hidden;
  background: #0f1115;
  color: #b8c0cc;
  font-family: Consolas, monospace;
  font-size: 12px;
}
.console-head {
  display: flex;
  gap: 12px;
  padding: 8px 14px;
  background: #171a21;
  color: #9aa4b2;
}
.console-head .pct {
  margin-left: auto;
  color: #4ade80;
}
.console-body {
  padding: 10px 14px;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
}

.sess-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 10px;
}
.sessions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sess {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  background: #fff;
  transition: background 0.15s ease;
}
html.dark .sess {
  background: #1c1c22;
}
.sess:hover {
  background: #f2f8f4;
}
html.dark .sess:hover {
  background: #23232a;
}
.sess.picked {
  background: rgba(7, 193, 96, 0.08);
}
html.dark .sess.picked {
  background: rgba(7, 193, 96, 0.16);
}
.sess-main {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.sess-name {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sess-summary {
  font-size: 12px;
  opacity: 0.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sess-side {
  text-align: right;
  flex: none;
}
.count {
  font-weight: 600;
  color: #07a04c;
}
html.dark .count {
  color: #4ade80;
}
.time {
  font-size: 12px;
  opacity: 0.45;
}

.export-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.mode-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mode-title {
  font-weight: 600;
  font-size: 13px;
}
.mode-desc {
  font-size: 12px;
  opacity: 0.55;
  white-space: normal;
  line-height: 1.5;
  margin-top: 2px;
}
.soft-card {
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
}
html.dark .soft-card {
  background: #1c1c22;
}
.fmt-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.path-text {
  font-size: 12px;
  font-family: Consolas, monospace;
  opacity: 0.65;
  word-break: break-all;
}
.export-actions {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-top: 18px;
}
.export-progress {
  display: flex;
  align-items: center;
  gap: 12px;
}
.files {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.file {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.file-path {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.footer {
  display: flex;
  align-items: center;
  padding: 26px 0 10px;
  position: sticky;
  bottom: 0;
  z-index: 5;
  background: linear-gradient(transparent, #f5f6f8 62%);
  backdrop-filter: blur(3px);
}
html.dark .footer {
  background: linear-gradient(transparent, #101014 62%);
}

.chat-view {
  max-height: 62vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}
.msg {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.msg.me {
  align-items: flex-end;
}
.msg .meta {
  font-size: 11px;
  opacity: 0.45;
  margin-bottom: 2px;
}
.bubble {
  max-width: 72%;
  background: #fff;
  border-radius: 10px;
  padding: 8px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  line-height: 1.6;
}
html.dark .bubble {
  background: #26262e;
}
.msg.me .bubble {
  background: #95ec69;
  color: #123;
}
.chat-img {
  max-width: 240px;
  border-radius: 8px;
  display: block;
  margin-top: 4px;
}
.sys-line {
  width: 100%;
  text-align: center;
  font-size: 12px;
  opacity: 0.45;
}
.record-view {
  max-height: 62vh;
  overflow: auto;
  padding-right: 4px;
}
.record-row {
  padding: 10px 0;
  border-bottom: 1px solid rgba(127, 127, 127, 0.15);
}
.record-row:last-child {
  border-bottom: none;
}
.rr-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  opacity: 0.55;
}
.rr-sender {
  font-weight: 600;
}
.rr-text {
  margin-top: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}
.rr-meta {
  display: flex;
  gap: 10px;
  font-size: 12px;
  opacity: 0.5;
  margin-top: 3px;
}
.rr-img {
  max-width: 240px;
  border-radius: 8px;
  margin-top: 6px;
  display: block;
}
</style>
