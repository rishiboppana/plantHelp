import { useEffect, useState } from 'react'
import { api } from './api.js'

const when = (d) => d.replace(' ', ' · ')

// Chat note shown under the reply when the model's schedule_reminders tool call created reminders
export function ReminderNote({ r }) {
  const once = r.added.filter((x) => !x.repeats); const rec = r.added.filter((x) => x.repeats)
  const names = [...new Set(rec.map((x) => x.title))]
  return (
    <div className="card">
      {r.added.length > 0 && <>
        <b>🔔 Added to Apple Reminders</b>
        <ul>{once.map((x, i) => <li key={i}>{x.title} — {when(x.due)}</li>)}
          {names.map((n) => <li key={n}>{n} — {rec.filter((x) => x.title === n).length} times, next {when(rec.find((x) => x.title === n).due)}</li>)}</ul></>}
      {r.errors?.length > 0 && <small>⚠️ Couldn't add {r.errors.length}: {r.errors[0].error}</small>}
    </div>
  )
}

export default function Reminders({ plantId, chatId }) {
  const [st, setSt] = useState(null); const [log, setLog] = useState([]); const [msg, setMsg] = useState('')
  const load = () => { api.reminderSettings().then(setSt).catch(() => {}); api.reminders(plantId).then(setLog).catch(() => {}) }
  useEffect(load, [plantId])
  const toggle = () => api.setReminderSettings(!st.auto).then(setSt)
  const fromChat = () => api.remindersFromChat(chatId).then((r) => { setMsg(`Added ${r.added.length}, ${r.already_scheduled.length} already there${r.errors.length ? `, ${r.errors.length} failed: ${r.errors[0].error}` : ''}`); load() })
    .catch(() => setMsg('No plan found in this chat yet'))
  return (
    <>
      <h3>Apple Reminders</h3>
      <p>When I give a plan or a follow-up ("water in 2 days", "mist every evening"), I add it to your Reminders app, in a list called PlantLens.</p>
      {st && !st.supported && <p>⚠️ Needs the backend to run on a Mac.</p>}
      {st && <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}><input type="checkbox" checked={st.auto} onChange={toggle} style={{ width: 'auto' }} />Add reminders automatically</label>}
      <button disabled={!chatId} onClick={fromChat}>Schedule the plan from this chat</button> <small>{msg}</small>
      <h4 className="tl-h">Created so far</h4>
      {!log.length && <p>Nothing yet.</p>}
      {log.map((l) => <div key={l.id} className="card entry"><small>{when(l.due)}</small><div>{l.title}</div></div>)}
    </>
  )
}
