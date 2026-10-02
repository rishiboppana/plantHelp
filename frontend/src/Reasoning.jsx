import { useState } from 'react'

// Shows only the one-line summary; tap it to see the full reasoning (everything after the "---" line).
export function splitReply(text = '') {
  const i = text.indexOf('\n---\n')
  return i < 0 ? { summary: text, detail: '' } : { summary: text.slice(0, i).trim(), detail: text.slice(i + 5).trim() }
}

// Turn bare URLs (the Sources line) into links; everything else stays plain text.
export function linkify(text = '') {
  return text.split(/(https?:\/\/[^\s,;)]+)/g).map((part, i) =>
    /^https?:\/\//.test(part) ? <a key={i} href={part} target="_blank" rel="noreferrer">{part.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</a> : part)
}

export default function Reasoning({ text, extra }) {
  const [open, setOpen] = useState(false)
  const { summary, detail } = splitReply(text)
  const has = !!detail || !!extra
  return (
    <div className="reasoning">
      <div className={has ? 'summary tap' : 'summary'} onClick={() => has && setOpen(!open)} title={has ? 'Tap to see the reasoning' : ''}>
        {summary}{has && <span className="chev">{open ? ' ▾' : ' ▸ why?'}</span>}
      </div>
      {open && <div className="detail">{linkify(detail)}{extra}</div>}
    </div>
  )
}
