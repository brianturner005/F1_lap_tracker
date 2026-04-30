import { useState, useEffect } from 'react'
import { RACES } from '../data/races'
import { DEFAULT_ORDER } from '../data/drivers'
import { getPicksForRace, savePickForRace } from '../utils/api'
import SortableList from './SortableList'

export default function PickEntry({ players }) {
  const [player, setPlayer] = useState('')
  const [raceId, setRaceId] = useState(RACES[0].id)
  const [order, setOrder] = useState([...DEFAULT_ORDER])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!player || !raceId) return
    setLoading(true)
    setError('')
    getPicksForRace(raceId)
      .then(picks => setOrder(picks[player] ? [...picks[player]] : [...DEFAULT_ORDER]))
      .catch(() => setError('Failed to load pick'))
      .finally(() => setLoading(false))
  }, [player, raceId])

  async function handleSave() {
    if (!player) return
    setSaving(true)
    setError('')
    try {
      await savePickForRace(raceId, player, order)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      setError('Failed to save — check your connection')
    } finally {
      setSaving(false)
    }
  }

  const race = RACES.find(r => r.id === raceId)

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <h2 className="text-lg font-bold text-white mb-1">Submit Pick</h2>
      <p className="text-f1muted text-sm mb-6">
        Drag drivers into your predicted finishing order, then save.
      </p>

      <div className="flex gap-3 mb-6 flex-wrap">
        <div className="flex-1 min-w-40">
          <label className="block text-xs text-f1muted mb-1 tracking-wider">PLAYER</label>
          <select
            value={player}
            onChange={e => setPlayer(e.target.value)}
            className="w-full bg-f1card border border-f1border rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-f1red"
          >
            <option value="">Select player…</option>
            {players.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div className="flex-1 min-w-52">
          <label className="block text-xs text-f1muted mb-1 tracking-wider">RACE</label>
          <select
            value={raceId}
            onChange={e => setRaceId(e.target.value)}
            className="w-full bg-f1card border border-f1border rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-f1red"
          >
            {RACES.map(r => <option key={r.id} value={r.id}>{r.country} {r.name}</option>)}
          </select>
        </div>
      </div>

      {!player ? (
        <div className="border border-dashed border-f1border rounded p-8 text-center text-f1muted text-sm">
          Select a player to load or start a pick.
        </div>
      ) : loading ? (
        <div className="text-center py-12 text-f1muted text-sm">Loading…</div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-f1muted tracking-wider">
              {race?.country} PREDICTED ORDER — {race?.name.toUpperCase()}
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
              disabled={saving}
              className="bg-f1red hover:bg-red-700 disabled:opacity-50 text-white font-medium text-sm px-6 py-2.5 rounded transition-colors"
            >
              {saving ? 'Saving…' : 'Save Pick'}
            </button>
            {saved && <span className="text-green-400 text-sm">Pick saved!</span>}
            {error && <span className="text-red-400 text-sm">{error}</span>}
          </div>
        </>
      )}
    </div>
  )
}
