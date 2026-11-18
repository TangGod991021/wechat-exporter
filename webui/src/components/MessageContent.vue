<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, fileUrl as mediaUrl, stickerUrl } from '../api'

const props = defineProps<{ msg: any; account?: string }>()
const emit = defineEmits<{
  (e: 'open-record', content: any): void
  (e: 'zoom', src: string): void
}>()

const kind = computed(() => props.msg?.kind || 'text')
const content = computed(() => props.msg?.content || {})
const records = computed<any[]>(() => content.value.records || [])
const cardKinds = [
  'miniprogram',
  'music',
  'video_share',
  'kf_template',
  'app',
]
const icons: Record<string, string> = {
  miniprogram: '🧩',
  music: '🎵',
  video_share: '🎬',
  chat_history: '💬',
  transfer: '💰',
  redpacket: '🧧',
  kf_template: '📢',
  app: '📦',
}
const icon = computed(() => icons[kind.value] || '📦')
const isWav = computed(() => (props.msg?.media || '').toLowerCase().endsWith('.wav'))
const fileUrl = computed(() => mediaUrl(props.msg.media))

const filePath = computed(() => content.value.file_path || '')
const fileName = computed(
  () => content.value.file_name || content.value.title || props.msg?.text || '附件',
)
const stickerFailed = ref(false)
const stickerSrc = computed(() => {
  if (props.msg?.media) return mediaUrl(props.msg.media)
  const md5 = content.value.md5 || content.value.sticker_md5 || ''
  const cdn = cleanUrl(content.value.cdnurl)
  if (props.account && (md5 || cdn)) return stickerUrl(props.account, md5, cdn)
  return ''
})
watch(stickerSrc, () => {
  stickerFailed.value = false
})

function fileUrlOf(p: string) {
  return mediaUrl(p)
}

function zoom(src?: string) {
  if (src) emit('zoom', src)
}

async function openFile() {
  if (!filePath.value) return
  try {
    const r = await api.openPath(filePath.value)
    if (!r.ok) window.alert('打开失败：' + (r.error || '未知错误'))
  } catch (e: any) {
    window.alert('打开失败：' + (e?.message || e))
  }
}

/** 微信内容可能被多次转义（&amp;amp;、&lt;/url&gt;），打开前统一还原 */
function deepUnescape(s: string) {
  let v = s || ''
  for (let i = 0; i < 3; i++) {
    const n = v
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;|&apos;/g, "'")
    if (n === v) break
    v = n
  }
  return v
}

function cleanUrl(u?: string) {
  const s = deepUnescape((u || '').trim())
  return s.split(/[\s<>"']/)[0]
}

function safeUrlOf(u?: string) {
  const s = cleanUrl(u)
  return s && /^(https?:|mailto:)/i.test(s) ? s : undefined
}

const safeUrl = computed(() => safeUrlOf(content.value.url))


const domain = computed(() => {
  const m = /^https?:\/\/([^/]+)/.exec(cleanUrl(content.value.url) || '')
  return m ? m[1] : ''
})

function escapeHtml(s: string) {
  return (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function linkify(s: string) {
  const esc = escapeHtml(s)
  return esc.replace(/(https?:\/\/[^\s<"]+)/g, (u) => {
    return `<a href="${u}" target="_blank" rel="noopener">${u}</a>`
  })
}
</script>

<template>
  <div class="mc">
    <!-- 引用 -->
    <template v-if="kind === 'quote'">
      <div class="quote">
        <div class="q-src">{{ content.quote?.sender }}</div>
        <div class="q-text">
          <a
            v-if="safeUrlOf(content.quote?.url)"
            :href="safeUrlOf(content.quote?.url)"
            target="_blank"
            rel="noopener noreferrer"
          >{{ content.quote.text }}</a>
          <span v-else>{{ content.quote?.text }}</span>
        </div>
      </div>
      <div class="reply" v-html="linkify(content.reply || msg.text)" />
    </template>

    <!-- 链接 -->
    <template v-else-if="kind === 'link'">
      <a
        class="card"
        :href="safeUrl"
        target="_blank"
        rel="noopener noreferrer"
      >
        <div class="card-title" v-html="linkify(content.title || content.url || msg.text)" />
        <div v-if="content.des" class="card-des">{{ content.des }}</div>
        <div v-if="domain" class="card-meta">{{ domain }}</div>
      </a>
    </template>

    <!-- 表情 -->
    <template v-else-if="kind === 'sticker'">
      <img
        v-if="stickerSrc && !stickerFailed"
        class="sticker-img"
        :src="stickerSrc"
        alt="表情"
        loading="lazy"
        @error="stickerFailed = true"
        @click="zoom(stickerSrc)"
      />
      <span v-else class="muted">[表情未下载]</span>
    </template>

    <!-- 文件 -->
    <template v-else-if="kind === 'file'">
      <div class="card">
        <div class="card-title">📄 {{ fileName }}</div>
        <div v-if="content.size" class="card-meta">{{ content.size }}</div>
        <div v-if="filePath" class="file-actions">
          <button class="mini-btn" type="button" @click="openFile">打开</button>
          <a class="mini-btn" :href="fileUrlOf(filePath)" :download="fileName">下载</a>
        </div>
        <div v-else class="card-meta warn">附件未缓存到本地</div>
      </div>
    </template>

    <!-- 转发聊天记录 -->
    <template v-else-if="kind === 'chat_history'">
      <div
        class="card"
        :class="{ clickable: records.length > 0 }"
        @click="records.length && emit('open-record', content)"
      >
        <div class="card-title">💬 {{ content.title || msg.text }}</div>
        <div v-if="content.des && !records.length" class="card-des">{{ content.des }}</div>
        <div class="card-meta">
          {{ records.length ? records.length + ' 条 · 点击查看详情' : msg.text }}
        </div>
      </div>
    </template>

    <!-- 名片 -->
    <template v-else-if="kind === 'card'">
      <div class="card">
        <div class="card-title">👤 {{ content.title || msg.text }}</div>
        <div v-if="content.des" class="card-meta">{{ content.des }}</div>
      </div>
    </template>

    <!-- 群公告 -->
    <template v-else-if="kind === 'announcement'">
      <div class="card">
        <div class="card-title">📢 {{ content.title || msg.text }}</div>
        <div v-if="content.des" class="card-des">{{ content.des }}</div>
      </div>
    </template>

    <!-- 位置 -->
    <template v-else-if="kind === 'location'">
      <a
        class="card"
        :href="content.url || undefined"
        target="_blank"
        rel="noopener noreferrer"
      >
        <div class="card-title">📍 {{ content.title || msg.text }}</div>
        <div v-if="content.des" class="card-meta">{{ content.des }}</div>
      </a>
    </template>

    <!-- 转账 -->
    <template v-else-if="kind === 'transfer'">
      <div class="card">
        <div class="card-title">💰 {{ content.amount || content.title || msg.text }}</div>
        <div v-if="content.memo" class="card-des">{{ content.memo }}</div>
        <div v-if="content.status" class="card-meta">{{ content.status }}</div>
      </div>
    </template>

    <!-- 红包 -->
    <template v-else-if="kind === 'redpacket'">
      <div class="card">
        <div class="card-title">🧧 {{ content.title || msg.text }}</div>
        <div v-if="content.memo" class="card-des">{{ content.memo }}</div>
        <div v-if="content.status || content.amount" class="card-meta">
          {{ content.status || content.amount }}
        </div>
      </div>
    </template>

    <!-- 小程序 / 音乐 / 视频分享等 -->
    <template v-else-if="cardKinds.includes(kind)">
      <div class="card">
        <div class="card-title">{{ icon }} {{ content.title || msg.text }}</div>
        <div v-if="content.des" class="card-des">{{ content.des }}</div>
        <div v-if="content.app" class="card-meta">{{ content.app }}</div>
      </div>
    </template>

    <!-- 视频 -->
    <template v-else-if="kind === 'video'">
      <video
        v-if="msg.media"
        class="chat-video"
        controls
        :src="fileUrl"
        :poster="msg.poster ? fileUrlOf(msg.poster) : undefined"
      />
      <span v-else>{{ msg.text }}</span>
    </template>

    <!-- 系统 / 拍一拍 / 不支持 -->
    <template v-else-if="['system', 'pat', 'unsupported'].includes(kind)">
      <div class="sys">{{ msg.text }}</div>
    </template>

    <!-- 普通文本 -->
    <template v-else>
      <span v-html="linkify(msg.text)" />
    </template>

    <img
      v-if="msg.media && !isWav && kind !== 'video' && kind !== 'sticker'"
      class="chat-img"
      :src="fileUrl"
      loading="lazy"
      @click="zoom(fileUrl)"
    />
    <template v-else-if="msg.media && kind !== 'video' && kind !== 'sticker'">
      <audio controls :src="fileUrl" />
      <a class="mini-btn muted" :href="fileUrl" download>下载语音</a>
    </template>
  </div>
</template>

<style scoped>
.mc {
  display: flex;
  flex-direction: column;
  gap: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}
a {
  color: #576b95;
  text-decoration: none;
}
.quote {
  background: rgba(127, 127, 127, 0.1);
  border-left: 3px solid rgba(127, 127, 127, 0.3);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  color: #888;
  max-width: 100%;
}
.q-src {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 2px;
}
.q-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.reply {
  white-space: pre-wrap;
  word-break: break-word;
}
.card {
  display: block;
  border: 1px solid rgba(127, 127, 127, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  background: rgba(127, 127, 127, 0.06);
  min-width: 180px;
  max-width: 420px;
  color: inherit;
}
.card-title {
  font-weight: 600;
  word-break: break-word;
}
.card-des {
  font-size: 12px;
  opacity: 0.7;
  margin-top: 4px;
  word-break: break-word;
}
.card-meta {
  font-size: 12px;
  opacity: 0.5;
  margin-top: 6px;
}
.card.clickable {
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.card.clickable:hover {
  border-color: rgba(7, 193, 96, 0.55);
}
.fallback-link {
  font-size: 12px;
  color: #07a04c;
  text-decoration: none;
  margin-top: 2px;
}
.fallback-link:hover {
  text-decoration: underline;
}
.card-meta.warn {
  color: #c33;
}
.sys {
  font-size: 12px;
  opacity: 0.55;
  text-align: center;
}
.chat-img {
  max-width: 240px;
  border-radius: 8px;
  display: block;
  cursor: zoom-in;
}
.sticker-img {
  max-width: 160px;
  max-height: 160px;
  object-fit: contain;
  display: block;
  cursor: zoom-in;
}
.sticker-img:hover {
  opacity: 0.9;
}
.file-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.mini-btn {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  font-size: 12px;
  border-radius: 999px;
  border: 1px solid rgba(7, 193, 96, 0.55);
  background: rgba(7, 193, 96, 0.08);
  color: #07a04c;
  cursor: pointer;
  text-decoration: none;
  line-height: 1.6;
}
.mini-btn:hover {
  background: rgba(7, 193, 96, 0.16);
}
.muted {
  font-size: 12px;
  opacity: 0.55;
}
.warn {
  color: #c33;
  opacity: 1;
}
.chat-video {
  max-width: 320px;
  border-radius: 8px;
  display: block;
  background: #000;
}
</style>
