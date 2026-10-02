import { useState } from 'react'
import { api } from './api.js'
import { Profile, Journal, Progress } from './Panels.jsx'

const LABEL = { green: 'Healthy', yellow: 'Needs attention', red: 'Urgent' }

// My plants: card grid -> click a plant for its full profile, journal and progress
export default function Garden({ plants, refresh, version, bump, chatWith }) {
  const [sel, setSel] = useState(null); const [name, setName] = useState(''); const [sub, setSub] = useState('Journal')
  const plant = plants.find((p) => p.id === sel)
  if (plant) return (
    <div className="gpage">
      <button onClick={() => setSel(null)}>← All plants</button>
      <div className="ghead">
        {plant.last_image ? <img src={`/uploads/${plant.last_image}`} alt="" /> : <div className="ph">🪴</div>}
        <div><h2>{plant.name}</h2><span className={`status ${plant.status}`}>{LABEL[plant.status]}</span></div>
        <button className="primary" style={{ marginLeft: 'auto' }} onClick={() => chatWith(plant.id)}>💬 Chat about this plant</button>
      </div>
      <div className="modes subtabs">{['Journal', 'Progress', 'About'].map((t) => <button key={t} className={sub === t ? 'on' : ''} onClick={() => setSub(t)}>{t}</button>)}</div>
      <div className="gbody">
        {sub === 'Journal' && <Journal plantId={plant.id} version={version} />}
        {sub === 'Progress' && <Progress plantId={plant.id} version={version} onChange={bump} />}
        {sub === 'About' && <Profile plant={plant} refresh={refresh} />}
      </div>
    </div>
  )
  return (
    <div className="gpage">
      <h2>My plants</h2>
      <div className="grid">
        {plants.map((p) => (
          <div key={p.id} className="pcard" onClick={() => setSel(p.id)}>
            {p.last_image ? <img src={`/uploads/${p.last_image}`} alt="" /> : <div className="ph">🪴</div>}
            <div className="pinfo">
              <b>{p.name}</b>
              <span className={`status ${p.status}`}>{LABEL[p.status]}</span>
              <small>{p.last_diagnosis || 'No diagnosis yet'}</small>
              <small>{p.diagnoses} check-ups · {p.open_events} to do{p.overdue_events > 0 && <b style={{ color: '#c0392b' }}> · ⏰ {p.overdue_events} overdue</b>}</small>
            </div>
          </div>
        ))}
        <div className="pcard add">
          <input placeholder="New plant name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="primary" onClick={() => name && api.addPlant(name).then(() => { setName(''); refresh() })}>＋ Add plant</button>
        </div>
      </div>
    </div>
  )
}
