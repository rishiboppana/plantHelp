import { useEffect, useState } from 'react'
import { api } from './api.js'
import { Profile, Journal, Progress, Plan } from './Panels.jsx'
import Weather from './Weather.jsx'
import Reminders from './Reminders.jsx'

import { CallList, ContextBar, TracePanel } from './Trace.jsx'

const TABS = [['Context', '🧠', 'Memory'], ['Trace', '🔬', 'Trace'], ['Plant', '🪴', 'Plant'], ['Journal', '📖', 'Journal'], ['Weather', '🌦️', 'Weather'], ['Progress', '📈', 'Progress'], ['Plan', '✅', 'Plan'], ['Reminders', '🔔', 'Remind'], ['Live', '🎥', 'Live']]

export default function Sidebar({ open, ctx, chatId, tr, busy, onRefresh, plants, plantId, refresh, version, bump }) {
  const [tab, setTab] = useState('Context')
  const plant = plants.find((p) => p.id === plantId)
  return (
    <aside className={`side ${open ? '' : 'closed'}`}>
      <div className="tabs">{TABS.map(([t, e, l]) => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}><span>{e}</span>{l}</button>)}</div>
      <div className="panel">
        {tab === 'Context' && <Context ctx={ctx} chatId={chatId} />}
        {tab === 'Trace' && <TracePanel tr={tr} busy={busy} onRefresh={onRefresh} version={version} />}
        {tab === 'Plant' && plant && <Profile plant={plant} refresh={refresh} />}
        {tab === 'Journal' && <Journal plantId={plantId} version={version} />}
        {tab === 'Weather' && plant && <Weather plant={plant} refresh={refresh} bump={bump} />}
        {tab === 'Progress' && <Progress plantId={plantId} version={version} onChange={bump} />}
        {tab === 'Plan' && <Plan plantId={plantId} onAdded={bump} />}
        {tab === 'Reminders' && <Reminders plantId={plantId} chatId={chatId} />}
        {tab === 'Live' && <><h3>Live camera</h3><p>Coming soon: I'll guide you around your plant in real time.</p><button disabled>Start camera</button></>}
      </div>
    </aside>
  )
}

function Context({ ctx, chatId }) {
  if (!ctx) return <><h3>Memory</h3><p>This shows how much I'm keeping in mind while we chat.</p></>
  const pct = (ctx.used / ctx.limit) * 100
  const n = (x) => Math.round(x || 0).toLocaleString()
  return (
    <>
      <h3>What I'm keeping in mind</h3>
      <div className="big" style={{ color: { ok: 'inherit', warn: '#c9a227', full: '#c0392b' }[ctx.level] }}>{pct < 10 ? pct.toFixed(1) : Math.round(pct)}%</div>
      <p>of this chat's context window is in use.{' '}
        {ctx.level === 'full' ? 'Nearly full: start a new chat soon or older details may be lost.' : ctx.level === 'warn' ? 'Getting full.' : 'Plenty of room left.'}</p>
      <ContextBar ctx={ctx} />
      {ctx.graph
        ? <><h4 className="tl-h">Memory graph</h4>
          <p><small>Condensed at turn {ctx.graph.built_turn} when the chat reached {n(ctx.graph.at_tokens)} tokens. Now each message gets only the matching part of this graph, not the whole chat.</small></p>
          <Graph chatId={chatId} version={`${ctx.graph.nodes}-${ctx.graph.edges}`} /></>
        : <p><small>The full conversation is sent each turn until it reaches {Math.round(0.85 * 100)}% of the window; then it is condensed into a memory graph.</small></p>}
      <h4 className="tl-h">Model calls in this chat</h4>
      <CallList calls={ctx.calls} limit={ctx.limit} />
      <p><small>{n(ctx.cumulative)} tokens spent in total over {ctx.turns} turn{ctx.turns === 1 ? '' : 's'} · largest call {n(ctx.peak)}</small></p>
      {ctx.model && <p><small>{ctx.model}</small></p>}
    </>
  )
}

const GCOL = { plant: '#2d6a4f', symptom: '#f4a261', cause: '#e76f51', action: '#457b9d', fact: '#e9c46a', advice: '#52b788', question: '#8e7dbe' }

function Graph({ chatId, version }) {
  const [g, setG] = useState(null)
  useEffect(() => { if (chatId) api.graph(chatId).then(setG).catch(() => {}) }, [chatId, version])
  if (!g) return null
  const nodes = Object.values(g.nodes); const W = 300, H = 260, R = 105
  const pos = Object.fromEntries(nodes.map((nd, i) => [nd.id, [W / 2 + R * Math.cos((2 * Math.PI * i) / nodes.length), H / 2 + R * Math.sin((2 * Math.PI * i) / nodes.length)]]))
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', background: 'rgba(0,0,0,.03)', borderRadius: 10 }}>
        {g.edges.map((e, i) => pos[e.s] && pos[e.t] && <line key={i} x1={pos[e.s][0]} y1={pos[e.s][1]} x2={pos[e.t][0]} y2={pos[e.t][1]} stroke="#999" strokeWidth="0.8"><title>{e.rel}</title></line>)}
        {nodes.map((nd) => <circle key={nd.id} cx={pos[nd.id][0]} cy={pos[nd.id][1]} r="6" fill={GCOL[nd.type] || '#999'}><title>{`${nd.type}: ${nd.text}`}</title></circle>)}
      </svg>
      <div className="legend">{Object.entries(GCOL).map(([k, c]) => <div key={k}><i style={{ background: c }} />{k}</div>)}</div>
    </>
  )
}
