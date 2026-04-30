import { useState } from 'react'
import { addPlayer, removePlayer } from '../utils/api'

export default function PlayerManager({ players, setPlayers }) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleAdd(e) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    if (players.includes(trimmed)) { setError('Name already exists'); return }
    if (players.length >= 10) { setError('Maximum 10 players'); return }
    setSaving(true)
    try {
      const updated = await addPlayer(trimmed)
      setPlayers(updated)
      setName('')
      setError('')
    } catch {
      setError('Failed to save — check your connection')
    } finally {
      setSaving(false)
    }
  }

  async function handleRemove(player) {
    try {
      const updated = await removePlayer(player)
      setPlayers(updated)
    } catch {
      setError('Failed to remove player')
    }
  }

  return (
    <div className="max-w-lg mx-auto py-10 px-4">
      <h2 className="text-lg font-bold text-white mb-1">League Players</h2>
      <p className="text-f1muted text-sm mb-6">Add everyone competing in your group.</p>

      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input
          value={name}
          onChange={e => { setName(e.target.value); setError('') }}
          placeholder="Player name"
          className="flex-1 bg-f1card border border-f1border rounded px-3 py-2 text-white placeholder-f1muted text-sm focus:outline-none focus:border-f1red"
        />
        <button
          type="submit"
          disabled={saving}
          className="bg-f1red hover:bg-red-700 disabled:opacity-50 text-white font-medium text-sm px-4 py-2 rounded transition-colors"
        >
          {saving ? '…' : 'Add'}
        </button>
      </form>

      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

      {players.length === 0 ? (
        <p className="text-f1muted text-sm text-center py-8 border border-dashed border-f1border rounded">
          No players yet — add one above.
        </p>
      ) : (
        <ul className="space-y-2">
          {players.map((player, i) => (
            <li key={player} className="flex items-center justify-between bg-f1card border border-f1border rounded px-4 py-3">
              <div className="flex items-center gap-3">
                <span className="text-f1muted text-xs w-5 text-right">{i + 1}</span>
                <span className="text-white font-medium">{player}</span>
              </div>
              <button
                onClick={() => handleRemove(player)}
                className="text-f1muted hover:text-red-400 transition-colors text-sm"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
