import { useState } from 'react'
import { Profile, Journal, Progress, Plan } from './Panels.jsx'
import Weather from './Weather.jsx'

import { ContextBar, TracePanel } from './Trace.jsx'

const TABS = [['Context', '🧠', 'Memory'], ['Trace', '🔬', 'Trace'], ['Plant', '🪴', 'Plant'], ['Journal', '📖', 'Journal'], ['Weather', '🌦️', 'Weather'], ['Progress', '📈', 'Progress'], ['Plan', '✅', 'Plan'], ['Live', '🎥', 'Live']]

export default function Sidebar({ open, ctx, tr, busy, onRefresh, plants, plantId, refresh, version, bump }) {
  const [tab, setTab] = useState('Context')
  const plant = plants.find((p) => p.id === plantId)
  return (
    <aside className={`side ${open ? '' : 'closed'}`}>
      <div className="tabs">{TABS.map(([t, e, l]) => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}><span>{e}</span>{l}</button>)}</div>
      <div className="panel">
        {tab === 'Context' && <Context ctx={ctx} />}
        {tab === 'Trace' && <TracePanel tr={tr} busy={busy} onRefresh={onRefresh} version={version} />}
        {tab === 'Plant' && plant && <Profile plant={plant} refresh={refresh} />}
        {tab === 'Journal' && <Journal plantId={plantId} version={version} />}
        {tab === 'Weather' && plant && <Weather plant={plant} refresh={refresh} bump={bump} />}
        {tab === 'Progress' && <Progress plantId={plantId} version={version} onChange={bump} />}
        {tab === 'Plan' && <Plan plantId={plantId} onAdded={bump} />}
        {tab === 'Live' && <><h3>Live camera</h3><p>Coming soon: I'll guide you around your plant in real time.</p><button disabled>Start camera</button></>}
      </div>
    </aside>
  )
}

function Context({ ctx }) {
  if (!ctx) return <><h3>Memory</h3><p>This shows how much I'm keeping in mind while we chat.</p></>
  const pct = Math.round((ctx.used / ctx.limit) * 100)
  return (
    <>
      <h3>What I'm keeping in mind</h3>
      <div className="big">{pct}%</div>
      <p>of my memory is in use. {pct > 80 ? 'Getting full — I may forget older bits.' : 'Plenty of room left.'}</p>
      <ContextBar ctx={ctx} />
      {ctx.model && <p>{ctx.model}</p>}
    </>
  )
}
