import { useEffect, useState } from 'react'
import { api } from './api.js'

const LABEL = { green: 'Healthy', yellow: 'Needs attention', red: 'Urgent' }
const img = (f) => f && `/uploads/${f}`

function PlantCard({ c, onOpen, onChat }) {
  const care = Object.entries(c.care)
  return (
    <div className="pcard fullcard" onClick={() => onOpen(c.id)}>
      {c.photo ? <img src={img(c.photo)} alt="" /> : <div className="ph">🪴</div>}
      <div className="pinfo">
        <b>{c.name}</b>{c.species && <small>{c.species}</small>}
        <span className={`status ${c.status}`}>{LABEL[c.status] || c.status}</span>
        {c.condition.checked
          ? <small>Checked {c.condition.checked}: {c.condition.symptoms.join(', ') || 'no clear symptoms'}{c.condition.possible_causes.length ? ` · maybe ${c.condition.possible_causes.join(', ')}` : ''}</small>
          : <small>No check-up yet</small>}
        {care.length > 0 && <div className="chips">{care.map(([k, v]) => <span key={k} className="chip" title={k}>{k}: {v}</span>)}</div>}
        {c.next && <small style={c.next.overdue ? { color: '#c0392b' } : {}}>{c.next.overdue ? '⏰ Overdue' : '📅 Next'}: {c.next.title} · {c.next.due}</small>}
        <small>{c.counts.checkups} check-ups · {c.counts.chats} chats · {c.counts.done} done · {c.counts.open} to do · since {c.since}</small>
        <div className="chips"><button onClick={(e) => { e.stopPropagation(); onChat(c.id) }}>💬 Chat</button></div>
      </div>
    </div>
  )
}

function ChatCard({ c, onOpen }) {
  return (
    <div className="pcard fullcard" onClick={() => onOpen(c.id)}>
      {c.photo ? <img src={img(c.photo)} alt="" /> : <div className="ph">💬</div>}
      <div className="pinfo">
        <b>{c.title}</b>
        <small>{c.plant || 'Plant'} · {c.messages} messages · {(c.updated || '').slice(0, 10)}</small>
        {c.status && <span className={`status ${c.status}`}>{LABEL[c.status]}</span>}
        {c.symptoms.length > 0 && <div className="chips">{c.symptoms.map((s) => <span key={s} className="chip">{s}</span>)}</div>}
        {c.asked && <small>You: “{c.asked}”</small>}
        {c.gist && <small>{c.gist}</small>}
      </div>
    </div>
  )
}

// Cards: one profile card per plant, one summary card per chat
export default function Cards({ version, openPlant, chatWith, openChat }) {
  const [plants, setPlants] = useState([]); const [chats, setChats] = useState([]); const [tab, setTab] = useState('plants')
  useEffect(() => { api.plantCards().then(setPlants).catch(() => {}); api.chatCards().then(setChats).catch(() => {}) }, [version])
  return (
    <div className="gpage">
      <h2>Cards</h2>
      <div className="modes subtabs">{[['plants', 'Plant profiles'], ['chats', 'Chats']].map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
      <div className="grid wide">
        {tab === 'plants' ? plants.map((c) => <PlantCard key={c.id} c={c} onOpen={openPlant} onChat={chatWith} />) : chats.map((c) => <ChatCard key={c.id} c={c} onOpen={openChat} />)}
      </div>
      {tab === 'chats' && !chats.length && <p>No chats yet.</p>}
    </div>
  )
}
