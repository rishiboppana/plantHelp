const j = (r) => r.json()
// the trace of the current chat turn; event actions (add / done / skip / delete) send it so they show up on its timeline
export const traceRef = { id: null }
const H = () => ({ 'Content-Type': 'application/json', ...(traceRef.id ? { 'X-Trace-Id': traceRef.id } : {}) })
const post = (u, b) => fetch(u, { method: 'POST', headers: H(), body: JSON.stringify(b) }).then(j)
const put = (u, b) => fetch(u, { method: 'PUT', headers: H(), body: JSON.stringify(b) }).then(j)

export const api = {
  plants: () => fetch('/api/plants').then(j),
  addPlant: (name, species = '') => post('/api/plants', { name, species }),
  setProfile: (id, p) => put(`/api/plants/${id}/profile`, p),
  setStatus: (id, status) => put(`/api/plants/${id}/status`, { status }),
  timeline: (id) => fetch(`/api/plants/${id}/timeline`).then(j),
  addEntry: (id, e) => post(`/api/plants/${id}/timeline`, e),
  upload: (file) => { const f = new FormData(); f.append('file', file); return fetch('/api/upload', { method: 'POST', body: f }).then(j) },
  conversations: (pid) => fetch(`/api/plants/${pid}/conversations`).then(j),
  newConversation: (pid) => post(`/api/plants/${pid}/conversations`, {}),
  conversation: (cid) => fetch(`/api/conversations/${cid}`).then(j),
  deleteConversation: (cid) => fetch(`/api/conversations/${cid}`, { method: 'DELETE' }).then(j),
  weather: (b) => post('/api/weather', b),
  chats: () => fetch('/api/conversations').then(j),
  newChat: (plant_id) => post(`/api/plants/${plant_id}/conversations`, {}),
  getChat: (id) => fetch(`/api/conversations/${id}`).then(j),
  delChat: (id) => fetch(`/api/conversations/${id}`, { method: 'DELETE' }).then(j),
  renameChat: (id, title) => put(`/api/conversations/${id}/title`, { title }),
  titleChat: (id) => fetch(`/api/conversations/${id}/title`, { method: 'POST' }).then(j),
  events: (id) => fetch(`/api/plants/${id}/events`).then(j),
  addEvent: (id, e) => post(`/api/plants/${id}/events`, e),
  updateEvent: (id, e) => put(`/api/events/${id}`, e),
  delEvent: (id) => fetch(`/api/events/${id}`, { method: 'DELETE', headers: H() }).then(j),
  trace: (id) => fetch(`/api/traces/${id}`).then(j),
  traces: (cid) => fetch(`/api/conversations/${cid}/traces`).then(j),
  analyze: (b) => post('/api/analyze', b),
  compare: (b) => post('/api/compare', b),
  plan: (b) => post('/api/plan', b),
  why: (b) => post('/api/why', b),
  graph: (cid) => fetch(`/api/conversations/${cid}/graph`).then(j),
  context: (b) => post('/api/context', b),
  // NDJSON stream: onEvent({type: conversation|context|span|token|done|error, ...})
  async chat(body, onEvent) {
    const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = ''
    for (;;) {
      const { done, value } = await reader.read(); if (done) break
      buf += dec.decode(value, { stream: true }); const lines = buf.split('\n'); buf = lines.pop()
      lines.filter(Boolean).forEach((l) => onEvent(JSON.parse(l)))
    }
  },
}
