const TOKEN = new URLSearchParams(window.location.search).get('token') || ''

function authHeaders(): Record<string, string> {
  return TOKEN ? { 'X-Auth-Token': TOKEN } : {}
}

/** 媒体文件直链（img/video/audio 无法带请求头，令牌走查询参数） */
export function fileUrl(path: string) {
  const base = '/api/file?path=' + encodeURIComponent(path)
  return TOKEN ? base + '&token=' + encodeURIComponent(TOKEN) : base
}

async function request(path: string, options: RequestInit = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...options,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  bootstrap: () => request('/api/bootstrap'),
  setConfig: (body: any) => request('/api/config', { method: 'POST', body: JSON.stringify(body) }),
  pickFolder: () => request('/api/pick-folder', { method: 'POST' }),
  locateWechat: () => request('/api/locate-wechat', { method: 'POST' }),
  startKeys: (account: string) =>
    request('/api/keys', { method: 'POST', body: JSON.stringify({ account }) }),
  startCore: (account: string) =>
    request('/api/core', { method: 'POST', body: JSON.stringify({ account }) }),
  prepare: (account: string, targets: string[], workers?: number) =>
    request('/api/prepare', {
      method: 'POST',
      body: JSON.stringify({ account, targets, workers }),
    }),
  startDecrypt: (account: string) =>
    request('/api/decrypt', { method: 'POST', body: JSON.stringify({ account }) }),
  startMedia: (
    account: string,
    images = true,
    hevc = true,
    voices = true,
    videos = true,
    workers?: number,
  ) =>
    request('/api/media', {
      method: 'POST',
      body: JSON.stringify({ account, images, hevc, voices, videos, workers }),
    }),
  sessions: (account: string) =>
    request('/api/sessions?account=' + encodeURIComponent(account)),
  chat: (
    account: string,
    username: string,
    limit = 100,
    before?: number,
    beforeId?: number,
  ) =>
    request(
      `/api/chat?account=${encodeURIComponent(account)}&username=${encodeURIComponent(
        username,
      )}&limit=${limit}` +
        (before !== undefined ? `&before=${before}` : '') +
        (beforeId !== undefined ? `&before_id=${beforeId}` : ''),
    ),
  startExport: (body: any) =>
    request('/api/export', { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => request('/api/jobs/' + id),
  cancelJob: (id: string) =>
    request('/api/jobs/' + id + '/cancel', { method: 'POST' }),
  openFolder: (path: string) =>
    request('/api/open-folder', { method: 'POST', body: JSON.stringify({ path }) }),
}

export async function waitJob(
  id: string,
  onTick?: (job: any) => void,
  interval = 500,
): Promise<any> {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const job = await api.job(id)
    onTick?.(job)
    if (job.status === 'done' || job.status === 'cancelled') return job
    if (job.status === 'error') throw new Error(job.error || '任务失败')
    await new Promise((r) => setTimeout(r, interval))
  }
}
