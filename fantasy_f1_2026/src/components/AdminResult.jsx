import { useState, useEffect } from 'react'
import { RACES } from '../data/races'
import { DEFAULT_ORDER } from '../data/drivers'
import { getResultForRace, saveResultForRace } from '../utils/storage'
import SortableList from './SortableList'

export default function AdminResult() {
  const [raceId, setRaceId] = useState(RACES[0].id)
  const [order, setOrder] = useState([...DEFAULT_ORDER])
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const existing = getResultForRace(raceId)
    setOrder(existing ? [...existing] : [...DEFAULT_ORDER])
    setSaved(false)
  }, [raceId])

  function handleSave() {
    saveResultForRace(raceId, order)
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  const race = RACES.find(r => r.id === raceId)

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <div className="flex items-start gap-3 mb-1">
        <h2 className="text-lg font-bold text-white">Enter Official Result</h2>
        <span className="mt-1 text-xs bg-f1red/20 text-f1red border border-f1red/30 rounded px-2 py-0.5 font-medium">
          ADMIN
        </span>
      </div>
      <p className="text-f1muted text-sm mb-6">
        Drag drivers into the actual finishing order. Scores are recalculated instantly on save.
      </p>

      <div className="mb-6">
        <label className="block text-xs text-f1muted mb-1 tracking-wider">RACE</label>
        <select
          value={raceId}
          onChange={e => setRaceId(e.target.value)}
          className="w-full max-w-xs bg-f1card border border-f1border rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-f1red"
        >
          {RACES.map(r => (
            <option key={r.id} value={r.id}>
              {r.country} {r.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-f1muted tracking-wider">
          {race?.country} OFFICIAL FINISHING ORDER — {race?.name.toUpperCase()}
        </p>
        <button
          onClick={() => setOrder([...DEFAULT_ORDER])}
          className="text-xs text-f1muted hover:text-white transition-colors"
        >
          Reset
        </button>
      </div>

      <SortableList order={order} setOrder={setOrder} />

      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={handleSave}
          className="bg-f1red hover:bg-red-700 text-white font-medium text-sm px-6 py-2.5 rounded transition-colors"
        >
          Confirm Result
        </button>
        {saved && (
          <span className="text-green-400 text-sm">Result saved — scores updated!</span>
        )}
      </div>
    </div>
  )
}
