// Left sidebar: new chat, chat history, and the My plants page
export default function LeftNav({ chats, chatId, view, setView, openChat, newChat, delChat, plants }) {
  const plantName = (id) => plants.find((p) => p.id === id)?.name
  return (
    <nav className="nav">
      <div className="brand">🌿 PlantLens</div>
      <button className="primary newchat" onClick={newChat}>＋ New chat</button>
      <button className={`navbtn ${view === 'garden' ? 'on' : ''}`} onClick={() => setView('garden')}>🪴 My plants</button>
      <div className="navlabel">Chats</div>
      <div className="chatlist">
        {!chats.length && <p className="hint">Your conversations will show up here.</p>}
        {chats.map((c) => (
          <div key={c.id} className={`chatrow ${view === 'chat' && c.id === chatId ? 'on' : ''}`} onClick={() => openChat(c.id)}>
            <div><div className="ctitle">{c.title}</div><small>{plantName(c.plant_id)}</small></div>
            <button className="x" title="Delete" onClick={(e) => { e.stopPropagation(); delChat(c.id) }}>✕</button>
          </div>
        ))}
      </div>
    </nav>
  )
}
