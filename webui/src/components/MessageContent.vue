<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ msg: any }>()
const emit = defineEmits<{ (e: 'open-record', content: any): void }>()

const kind = computed(() => props.msg?.kind || 'text')
const content = computed(() => props.msg?.content || {})
const records = computed<any[]>(() => content.value.records || [])
const cardKinds = [
  'miniprogram',
  'music',
  'video_share',
  'transfer',
  'redpacket',
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
const fileUrl = computed(() => '/api/file?path=' + encodeURIComponent(props.msg.media))

function fileUrlOf(p: string) {
  return '/api/file?path=' + encodeURIComponent(p)
}

const domain = computed(() => {
  const m = /^https?:\/\/([^/]+)/.exec(content.value.url || '')
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
        <div class="q-text">{{ content.quote?.text }}</div>
      </div>
      <div class="reply" v-html="linkify(content.reply || msg.text)" />
    </template>

    <!-- 链接 -->
    <template v-else-if="kind === 'link'">
      <a
        class="card"
        :href="content.url || undefined"
        target="_blank"
        rel="noopener"
      >
        <div class="card-title" v-html="linkify(content.title || content.url || msg.text)" />
        <div v-if="content.des" class="card-des">{{ content.des }}</div>
        <div v-if="domain" class="card-meta">{{ domain }}</div>
      </a>
    </template>

    <!-- 文件 -->
    <template v-else-if="kind === 'file'">
      <div class="card">
        <div class="card-title">📄 {{ content.title }}</div>
        <div v-if="content.size" class="card-meta">{{ content.size }}</div>
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

    <!-- 小程序 / 音乐 / 转账 / 红包等 -->
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
      v-if="msg.media && !isWav && kind !== 'video'"
      class="chat-img"
      :src="fileUrl"
      loading="lazy"
    />
    <audio v-else-if="msg.media && kind !== 'video'" controls :src="fileUrl" />
  </div>
</template>

<style scoped>
.mc {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
.sys {
  font-size: 12px;
  opacity: 0.55;
  text-align: center;
}
.chat-img {
  max-width: 240px;
  border-radius: 8px;
  display: block;
}
.chat-video {
  max-width: 320px;
  border-radius: 8px;
  display: block;
  background: #000;
}
</style>
