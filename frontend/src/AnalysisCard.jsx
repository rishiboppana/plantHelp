import { useState } from 'react'
// Friendly photo-check result: one card, details tucked into expandable sections
const HUES = [8, 38, 200, 280, 330, 160]   // one hue per symptom so boxes and legend match
const STATUS = { green: ['🌱', 'Looking good — just keep an eye on it'], yellow: ['🌤️', 'Needs a little attention soon'], red: ['🚨', 'Needs attention today'] }

export default function AnalysisCard({ a, imageUrl, onAsk }) {
  const [emoji, msg] = STATUS[a.urgency] || STATUS.green
  const [showMap, setShowMap] = useState(true)
  const kinds = [...new Set(a.regions?.map((r) => r.symptom))]
  const hue = (r) => HUES[kinds.indexOf(r.symptom) % HUES.length]
  return (
    <div className="card">
      <div className={`status ${a.urgency}`}><span>{emoji}</span>{msg}</div>
      {imageUrl && (
        <>
          <div className="mapwrap">
            <img src={imageUrl} alt="" />
            {showMap && a.regions?.map((r, i) => (
              <div key={i} className="region" title={r.label} style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%`, '--h': hue(r) }} />
            ))}
          </div>
          {a.regions?.length > 0 && (
            <div className="maplegend">
              <button onClick={() => setShowMap(!showMap)}>{showMap ? 'Hide' : 'Show'} symptom map</button>
              {showMap && kinds.map((k) => <span key={k} className="chip" style={{ '--h': hue({ symptom: k }) }}><i />{a.regions.find((r) => r.symptom === k).label}</span>)}
            </div>
          )}
        </>
      )}
      {a.diagnosis && <div className={`dx ${a.diagnosis.status}`}>
        <b>{{ confirmed: '✅ Confirmed', likely: '🔎 Most likely', undetermined: '❔ Not sure yet' }[a.diagnosis.status]}</b> {a.diagnosis.headline}
        {a.diagnosis.supporting?.length > 0 && <div><small>Supported by: {a.diagnosis.supporting.join('; ')}</small></div>}
        {a.diagnosis.confirm?.length > 0 && <div><small>Tap to answer and confirm:</small>
          {a.diagnosis.confirm.map((c) => <div key={c.question} className="chips"><span>{c.question}</span>
            {['Yes', 'No'].map((v) => <button key={v} onClick={() => onAsk?.(`${v}. ${c.question.replace(/\?$/, '')}`, 'answer')}>{v}</button>)}</div>)}
        </div>}
      </div>}
      <div className="chips">{a.symptoms?.map((s) => <span key={s} className="chip">{s}</span>)}</div>
      {a.uncertainty && <p>🤔 {a.uncertainty}</p>}
      <h4>What to do next</h4>
      <ul>{a.checklist?.map((c) => <li key={c}>{c}</li>)}</ul>
      {a.followup && <p>📅 I scheduled a re-check in {a.followup.days} day{a.followup.days === 1 ? '' : 's'}. You'll find it under Progress{a.followup.apple?.added?.length ? ' and in Apple Reminders' : ''}.</p>}
      {a.questions?.length > 0 && <div className="optional"><h4>Optional: tell me any of these for a better answer</h4>
        <ul>{a.questions.map((q) => <li key={q}>{q}</li>)}</ul></div>}
      <details><summary>What could be causing it</summary>
        <ul>{a.possibilities?.map((p) => <li key={p.cause}>{p.cause} — {p.likelihood}</li>)}</ul></details>
      {a.pests?.length > 0 && <details><summary>Possible pests</summary><ul>{a.pests.map((p) => <li key={p.name}>{p.name}: {p.check}</li>)}</ul></details>}
      {a.healthy_signs?.length > 0 && <details><summary>Healthy signs</summary><ul>{a.healthy_signs.map((s) => <li key={s}>{s}</li>)}</ul></details>}
      {a.references?.length > 0 && <details><summary>Where this comes from</summary><ul>{a.references.map((r) => <li key={r.title}><a href={r.url}>{r.title}</a> — {r.snippet}</li>)}</ul></details>}
      {a.stub && <div className="stub">sample data — real analysis coming</div>}
    </div>
  )
}
