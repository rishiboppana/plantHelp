import { Fragment, useEffect, useRef, useState } from 'react'
import { api, traceRef } from './api.js'
import Sidebar from './Sidebar.jsx'
import LeftNav from './LeftNav.jsx'
import Garden from './Garden.jsx'
import AnalysisCard from './AnalysisCard.jsx'
import Reasoning from './Reasoning.jsx'

const MODES = [['normal', 'Check-up'], ['rescue', 'SOS'], ['healthy', 'Healthy']]

export default function App() {
  const [plants, setPlants] = useState([]); const [plantId, setPlantId] = useState(1)
  const [chats, setChats] = useState([]); const [chatId, setChatId] = useState(null); const [view, setView] = useState('chat')
  const [items, setItems] = useState([]) // {role, content, image?, url?} | {analysis, url}
  const [input, setInput] = useState(''); const [pending, setPending] = useState(null) // {image, url}
  const [mode, setMode] = useState('normal'); const [ctx, setCtx] = useState(null); const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(true); const [version, setVersion] = useState(0)
  const [tr, setTr] = useState(null) // trace of the latest turn: {id, spans: [...]}, filled live while the reply is being made
  const fileRef = useRef(); const endRef = useRef(); const chatRef = useRef()

  // uploaded photos shrink toward the top-right as you scroll down, and grow back as you scroll up
  function shrinkPhotos(chat) {
    if (!chat) return
    const st = chat.scrollTop; const anchors = [...chat.querySelectorAll('.photoanchor')]
    let active = -1
    anchors.forEach((a, i) => { if (a.offsetTop <= st + 8) active = i })
    anchors.forEach((a, i) => {
      const ph = a.nextElementSibling; if (!ph) return
      ph.style.setProperty('--s', Math.max(0.28, Math.min(1, 1 - (st - a.offsetTop) / 260)))
      ph.style.opacity = i < active ? 0 : 1          // only the newest scrolled-past photo stays docked
    })
  }
  useEffect(() => { shrinkPhotos(chatRef.current) }, [items])

  const lastImage = [...items].reverse().find((m) => m.url)?.url // newest photo stays pinned above the chat
  const refresh = () => api.plants().then(setPlants)
  const refreshChats = () => api.chats().then(setChats)
  const bump = () => { setVersion((v) => v + 1); refresh() }
  useEffect(() => { refresh(); refreshChats() }, [])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [items])
  const msgs = (list) => list.filter((m) => m.role).map(({ role, content, image }) => ({ role, content, image }))
  // the meter is the server's saved ledger for this conversation: reload it on open / new chat and after every turn (never mid-turn: live spans own it then)
  const busyRef = useRef(false); busyRef.current = busy
  const refreshCtx = (cid, force) => api.context({ conversation_id: cid || 0, plant_id: plantId }).then((c) => { if (force || !busyRef.current) setCtx(c) }).catch(() => {})
  useEffect(() => { refreshCtx(chatId) }, [chatId])
  const loadTrace = (id) => api.trace(id).then((t) => setTr((cur) => (cur?.id === id || !cur ? t : cur))).catch(() => {})
  const addSpan = (sp) => {   // spans arrive twice (started, finished): merge by id
    setTr((cur) => { if (!cur) return cur; const i = cur.spans.findIndex((x) => x.id === sp.id); const spans = [...cur.spans]; if (i < 0) spans.push(sp); else spans[i] = sp; return { ...cur, spans } })
    if (sp.kind === 'context' && 'segments' in sp.attrs) setCtx((c) => ({ ...c, ...sp.attrs }))
  }
  const newChat = (pid = plantId) => { setTr(null); refreshCtx(0, true); traceRef.id = null; setChatId(null); setItems([]); setPending(null); setPlantId(pid); setView('chat') }
  async function openChat(id) {
    const c = await api.getChat(id)
    const meta = chats.find((x) => x.id === id)
    setChatId(id); setPlantId(meta?.plant_id ?? plantId); setView('chat')
    api.traces(id).then((l) => { setTr(l[0] || null); traceRef.id = l[0]?.id || null }).catch(() => {})
    setItems(c.messages.map((m) => m.analysis ? { analysis: m.analysis, url: m.url } : { role: m.role, content: m.content, image: m.image, url: m.url }))
  }
  async function delChat(id) { await api.delChat(id); if (id === chatId) newChat(); refreshChats() }

  async function pick(e) {
    const f = e.target.files[0]; if (!f) return
    setPending(await api.upload(f)); e.target.value = ''
  }

  async function send(text = input, skill = '') {   // skill 'diagnose' forces the check-up (also: type /diagnose)
    if (busy || (!text.trim() && !pending && !skill)) return
    let cid = chatId
    if (!cid) { cid = (await api.newChat(plantId)).id; setChatId(cid) }  // created first so the photo analysis and the chat share one saved conversation
    const user = { role: 'user', content: text, image: pending?.image, url: pending?.url }
    const next = [...items, user, { role: 'assistant', content: '' }]
    const slot = next.length - 1
    const tid = Math.random().toString(36).slice(2, 14)    // one trace per send: the photo analysis and the chat reply both log to it
    traceRef.id = tid; setTr({ id: tid, spans: [] })
    setItems(next); setInput(''); setPending(null); setBusy(true)
    const img = user.image || (skill && [...items].reverse().find((m) => m.image)?.image)   // a re-check reuses the last photo
    if (img) api.analyze({ plant_id: plantId, image: img, conversation_id: cid, text, skill, trace_id: tid }).then((a) => {
      loadTrace(tid)
      if (a.skipped) return
      setItems((cur) => [...cur, { analysis: a, url: user.url || lastImage }]); bump()
    }).catch(() => loadTrace(tid))
    try {
      await api.chat({ plant_id: plantId, conversation_id: cid, messages: msgs([...items, user]), mode, skill, trace_id: tid }, (ev) => {
        if (ev.type === 'token') setItems((cur) => { const c = [...cur]; c[slot] = { ...c[slot], content: c[slot].content + ev.text }; return c })
        else if (ev.type === 'span') addSpan(ev.span)
        else if (ev.type === 'context') setCtx(ev)
        else if (ev.type === 'error') setItems((cur) => { const c = [...cur]; c[slot] = { role: 'assistant', content: ev.text }; return c })
      })
    } finally {
      setBusy(false); loadTrace(tid); refreshCtx(cid, true)
      const turns = next.filter((m) => m.role === 'user').length
      refreshChats()
      if (turns === 1 || turns === 3) api.titleChat(cid).then(refreshChats)
    }
  }


  return (
    <div className="app">
      <LeftNav chats={chats} chatId={chatId} view={view} setView={setView} openChat={openChat} newChat={() => newChat()} delChat={delChat} plants={plants} />
      <div className="main">
        {view === 'garden'
          ? <Garden plants={plants} refresh={refresh} version={version} bump={bump} chatWith={(pid) => newChat(pid)} />
          : <>
            <div className="top">
              <select value={plantId} disabled={!!items.length} title="Which plant is this chat about?" onChange={(e) => setPlantId(+e.target.value)}>{plants.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
              <div className="modes">{MODES.map(([k, l]) => <button key={k} className={mode === k ? 'on' : ''} onClick={() => setMode(k)}>{l}</button>)}</div>
              <button className="toggle" style={{ marginLeft: 'auto' }} onClick={() => setOpen(!open)}>{open ? 'Hide panel' : '🧠 Panel'}</button>
            </div>
            <div className="chat" ref={chatRef} onScroll={(e) => shrinkPhotos(e.currentTarget)}>
              {!items.length && <div className="hero">
                <div className="leaf">🌿</div><h2>How's your plant doing?</h2><p>Snap or upload a photo and we'll figure it out together.</p>
                <button className="drop" onClick={() => fileRef.current.click()}><span>📷</span>Add a photo</button>
                <div className="hints">{['Why are the leaves yellow?', 'Is my plant getting enough water?'].map((h) => <button key={h} onClick={() => send(h)}>{h}</button>)}</div>
              </div>}
              {items.map((m, i) => m.analysis
                ? <AnalysisCard key={i} a={m.analysis} imageUrl={m.url} onAsk={send} />
                : (m.content || m.url) && <Fragment key={i}>
                    {m.url && m.role === 'user' && <><div className="photoanchor" /><div className="photo"><img src={m.url} alt="" /></div></>}
                    {(m.content || m.role !== 'user') && <div className={`msg ${m.role}`}>
                      {m.url && m.role !== 'user' && <img src={m.url} alt="" />}
                      {m.role === 'assistant' ? <Reasoning text={m.content} /> : m.content}
                    </div>}
                  </Fragment>)}
              <div ref={endRef} />
            </div>
            <div className="composer">
              <input ref={fileRef} type="file" accept="image/*" hidden onChange={pick} />
              <button className="round" title="Add photo" onClick={() => fileRef.current.click()}>📷</button>
              {pending && <img className="thumb" src={pending.url} alt="" />}
              <textarea rows={1} value={input} placeholder="Ask anything about your plant, or type /diagnose…" onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
              <button className="round" title="Run a plant check-up on the photo (or type /diagnose)" disabled={busy} onClick={() => send(input, 'diagnose')}>🩺</button>
              <button className="primary round" disabled={busy} onClick={() => send()}>➤</button>
            </div>
          </>}
      </div>
      {view === 'chat' && <Sidebar open={open} ctx={ctx} chatId={chatId} tr={tr} busy={busy} onRefresh={() => tr && loadTrace(tr.id)} plants={plants} plantId={plantId} refresh={refresh} version={version} bump={bump} />}
    </div>
  )
}
