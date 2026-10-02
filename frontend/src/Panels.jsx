import { useEffect, useState } from 'react'
import { api } from './api.js'

// local calendar dates: toISOString() is UTC, which is already "tomorrow" in the evening west of Greenwich
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const today = () => ymd(new Date())
const inDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return ymd(d) }

export function Profile({ plant, refresh }) {
  const [p, setP] = useState({}); const [saved, setSaved] = useState('')
  // reload when the saved profile changes (e.g. the weather check fills in location), not only when switching plants; otherwise Save would overwrite it with stale values
  useEffect(() => { try { setP(JSON.parse(plant.profile || '{}')) } catch { setP({}) } }, [plant.id, plant.profile])
  const save = () => api.setProfile(plant.id, p).then(refresh).then(() => { setSaved('Saved ✓'); setTimeout(() => setSaved(''), 2000) }).catch(() => setSaved('Could not save'))
  const fields = ['species', 'light', 'watering', 'location', 'soil', 'recent changes', 'temperature', 'humidity', 'indoor/outdoor', 'recent weather']
  return (
    <>
      <h3>About {plant.name}</h3><p>The more I know, the better my advice.</p>
      {fields.map((f) => <label key={f}>{f}<input value={p[f] || ''} onChange={(e) => setP({ ...p, [f]: e.target.value })} /></label>)}
      <button className="primary" onClick={save}>Save</button> <small>{saved}</small>
    </>
  )
}

// Journal = the detailed written record: full diagnosis notes + your own notes.
export function Journal({ plantId, version }) {
  const [items, setItems] = useState([]); const [text, setText] = useState('')
  const load = () => api.timeline(plantId).then(setItems)
  useEffect(() => { load() }, [plantId, version])
  return (
    <>
      <h3>Plant journal</h3><p>Detailed diagnosis notes are saved here automatically.</p>
      <input placeholder="Write a note…" value={text} onChange={(e) => setText(e.target.value)} />
      <button onClick={() => text && api.addEntry(plantId, { kind: 'note', text }).then(() => { setText(''); load() })}>Add note</button>
      {!items.length && <p>No entries yet — upload a photo to get your first diagnosis.</p>}
      {items.map((i) => {
        const a = i.kind === 'check-up' && i.analysis ? JSON.parse(i.analysis) : null
        return (
          <div key={i.id} className="card entry">
            <small>{i.created.slice(0, 16)} · {{ 'check-up': '📷 Photo check-up', diagnosis: '🔍 Diagnosis' }[i.kind] || '📝 Note'}</small>
            {i.image && <img className="entryimg" src={`/uploads/${i.image}`} alt="" />}
            <div>{i.text}</div>
            {a && <details><summary>Full notes</summary>
              <b>Possible causes</b><ul>{(a.possibilities || []).map((p) => <li key={p.cause}>{p.cause} — {p.likelihood}</li>)}</ul>
              <b>Suggested actions</b><ul>{(a.checklist || []).map((c) => <li key={c}>{c}</li>)}</ul>
              {a.uncertainty && <p>{a.uncertainty}</p>}</details>}
          </div>
        )
      })}
    </>
  )
}

// Progress = everything that happened or is planned, with what came of it.
export function Progress({ plantId, version, onChange }) {
  const [ev, setEv] = useState([]); const [title, setTitle] = useState(''); const [due, setDue] = useState(today())
  const [cmp, setCmp] = useState(null)
  const load = () => api.events(plantId).then(setEv)
  useEffect(() => { load() }, [plantId, version])
  const upd = (e, patch) => api.updateEvent(e.id, { ...e, ...patch }).then(() => { load(); onChange?.() })
  const snooze = (e, days) => api.snooze(e.id, days).then(() => { load(); onChange?.() })
  const upcoming = ev.filter((e) => e.status === 'planned'); const done = ev.filter((e) => e.status !== 'planned').reverse()
  return (
    <>
      <h3>Progress</h3><p>Plan what to do, then record how it went.</p>
      <Memory plantId={plantId} version={version} />
      <input placeholder="e.g. Repot into a bigger pot" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      <button className="primary" onClick={() => title && api.addEvent(plantId, { title, due, source: 'manual' }).then(() => { setTitle(''); load(); onChange?.() })}>Add to plan</button>
      <h3>Coming up</h3>
      {!upcoming.length && <p>Nothing planned.</p>}
      {upcoming.map((e) => <EventRow key={e.id} e={e} onSnooze={(d) => snooze(e, d)} onSave={(r) => upd(e, { status: 'done', result: r })} onSkip={() => upd(e, { status: 'skipped' })} onDel={() => api.delEvent(e.id).then(() => { load(); onChange?.() })} />)}
      <h3>What happened</h3>
      {!done.length && <p>Finished steps and their results show up here.</p>}
      {done.map((e) => <div key={e.id} className="card entry"><small>{(e.done_at || e.due || '').slice(0, 10)} · {e.status === 'done' ? '✅ Done' : '⏭️ Skipped'}</small><b>{e.title}</b>{e.result && <div>Result: {e.result}</div>}</div>)}
      <button onClick={() => api.compare({ plant_id: plantId }).then(setCmp)}>📈 Compare latest photos</button>
      {cmp && <div className="card"><span className="badge">{cmp.trend}</span><p>{cmp.summary}</p>{cmp.stub && <div className="stub">sample data</div>}</div>}
    </>
  )
}

function EventRow({ e, onSave, onSkip, onDel, onSnooze }) {
  const [res, setRes] = useState(''); const [open, setOpen] = useState(false)
  const overdue = e.due && e.due < today()
  return (
    <div className="card entry">
      <small>{overdue ? '⏰ Overdue · ' : e.due === today() ? '🔔 Due today · ' : '🗓️ '}{e.due}{e.kind === 'recheck' ? ' · 📷 follow-up' : ''}</small><b>{e.title}</b>
      {open
        ? <><input placeholder="How did it go?" value={res} onChange={(x) => setRes(x.target.value)} /><div className="chips"><button className="primary" onClick={() => onSave(res)}>Save result</button></div></>
        : <div className="chips"><button onClick={() => setOpen(true)}>Mark done</button><button onClick={() => onSnooze(1)}>Snooze 1d</button><button onClick={() => onSnooze(3)}>3d</button><button onClick={onSkip}>Skip</button><button onClick={onDel}>Delete</button></div>}
    </div>
  )
}

// Structured memory: what I currently know about this plant, in one place.
export function Memory({ plantId, version }) {
  const [m, setM] = useState(null)
  useEffect(() => { api.memory(plantId).then(setM).catch(() => setM(null)) }, [plantId, version])
  if (!m) return null
  const known = Object.entries(m.profile)
  return (
    <details className="card" open>
      <summary><b>What I know about {m.plant.name}</b></summary>
      {m.condition.checked
        ? <p>Last check-up {m.condition.checked.slice(0, 10)}: {m.condition.symptoms.join(', ') || 'no clear symptoms'}{m.condition.possible_causes.length ? ` · possible: ${m.condition.possible_causes.join(', ')}` : ''}</p>
        : <p>No check-up yet.</p>}
      {known.length > 0 && <p><small>{known.map(([k, v]) => `${k}: ${v}`).join(' · ')}</small></p>}
      {m.tried.length > 0 && <><b>Tried</b><ul>{m.tried.map((e, i) => <li key={i}>{e.title} — {e.status}{e.result ? `: ${e.result}` : ''}</li>)}</ul></>}
      {m.next.length > 0 && <><b>Next</b><ul>{m.next.map((e, i) => <li key={i}>{e.title} — {e.due}</li>)}</ul></>}
    </details>
  )
}

export function Plan({ plantId, onAdded }) {
  const [r, setR] = useState(null)
  const add = async () => {
    const rows = [...r.today.map((t) => [t, today()]), ...r.next_days.map((t) => [t, inDays(3)]), ...r.next_week.map((t) => [t, inDays(7)])]
    for (const [title, due] of rows) await api.addEvent(plantId, { title, due, source: 'manual' })
    onAdded?.()
  }
  const L = ({ t, a }) => <div className="card"><h4>{t}</h4><ul>{a.map((x) => <li key={x}>{x}</li>)}</ul></div>
  return (
    <>
      <h3>Recovery plan</h3>
      <button onClick={() => api.plan({ plant_id: plantId }).then(setR)}>Generate plan</button>
      {r && <><L t="Today" a={r.today} /><L t="Next few days" a={r.next_days} /><L t="Next week" a={r.next_week} />
        <button className="primary" onClick={add}>Add all to Progress</button>{r.stub && <div className="stub">sample data</div>}</>}
    </>
  )
}
