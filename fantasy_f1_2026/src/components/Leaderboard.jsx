import { useState } from 'react'
import { RACES } from '../data/races'
import { DRIVERS } from '../data/drivers'
import { getAllPicks, getAllResults, getPicksForRace } from '../utils/storage'
import { computeSeasonScores, scorePickAgainstResult } from '../utils/scoring'

function medal(rank) {
  if (rank === 1) return '🥇'
  if (rank === 2) return '🥈'
  if (rank === 3) return '🥉'
  return `${rank}.`
}

function RaceBreakdown({ player, raceId }) {
  const result = getAllResults()[raceId]
  const picks = getPicksForRace(raceId)[player]

  if (!result) {
    return <p className="text-f1muted text-xs px-4 py-2">No result entered yet.</p>
  }
  if (!picks) {
    return <p className="text-f1muted text-xs px-4 py-2">No pick submitted for this race.</p>
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-f1muted">
          <th className="text-left px-4 py-1.5 font-medium">Pos</th>
          <th className="text-left px-4 py-1.5 font-medium">Driver</th>
          <th className="text-left px-4 py-1.5 font-medium">Predicted</th>
          <th className="text-right px-4 py-1.5 font-medium">Pts</th>
        </tr>
      </thead>
      <tbody>
        {result.map((driverId, actualIdx) => {
          const driver = DRIVERS.find(d => d.id === driverId)
          const predictedIdx = picks.indexOf(driverId)
          const diff = predictedIdx === -1 ? null : Math.abs(predictedIdx - actualIdx)
          const pts = predictedIdx === -1 ? 0 : (diff === 0 ? 25 : diff === 1 ? 10 : diff === 2 ? 5 : diff === 3 ? 2 : 0)
          return (
            <tr key={driverId} className="border-t border-f1border/50 hover:bg-white/5">
              <td className="px-4 py-1.5 text-f1muted">{actualIdx + 1}</td>
              <td className="px-4 py-1.5 text-white">{driver?.name ?? driverId}</td>
              <td className="px-4 py-1.5 text-f1muted">
                {predictedIdx === -1 ? '—' : `P${predictedIdx + 1}`}
                {diff != null && diff > 0 && (
                  <span className="text-f1muted/60 ml-1">(±{diff})</span>
                )}
                {diff === 0 && <span className="text-green-400 ml-1">✓</span>}
              </td>
              <td className={`px-4 py-1.5 text-right font-medium ${pts > 0 ? 'text-white' : 'text-f1muted'}`}>
                {pts > 0 ? `+${pts}` : '0'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function PlayerRow({ rank, player, data, allResults }) {
  const [expandedRace, setExpandedRace] = useState(null)

  const racesWithResults = RACES.filter(r => allResults[r.id])

  return (
    <div className="border border-f1border rounded overflow-hidden">
      <div className="flex items-center gap-4 px-4 py-3 bg-f1card">
        <span className="text-lg w-8 text-center">{medal(rank)}</span>
        <span className="text-white font-semibold flex-1">{player}</span>
        <div className="text-right">
          <p className="text-white font-bold text-lg leading-none">{data.total}</p>
          <p className="text-f1muted text-xs">pts</p>
        </div>
      </div>

      {racesWithResults.length > 0 && (
        <div className="px-4 py-2 bg-f1dark/50 flex flex-wrap gap-1">
          {racesWithResults.map(race => {
            const pts = data.races[race.id] ?? null
            const isExpanded = expandedRace === race.id
            return (
              <button
                key={race.id}
                onClick={() => setExpandedRace(isExpanded ? null : race.id)}
                className={`flex items-center gap-1 text-xs rounded px-2 py-1 border transition-colors ${
                  isExpanded
                    ? 'bg-f1red/20 border-f1red/50 text-white'
                    : 'bg-f1card border-f1border text-f1muted hover:text-white'
                }`}
              >
                <span>{race.country}</span>
                <span className={pts != null ? 'text-white font-medium' : 'text-f1muted'}>
                  {pts != null ? `${pts}` : '–'}
                </span>
              </button>
            )
          })}
        </div>
      )}

      {expandedRace && (
        <div className="border-t border-f1border bg-f1dark/30">
          <RaceBreakdown player={player} raceId={expandedRace} />
        </div>
      )}
    </div>
  )
}

export default function Leaderboard({ players }) {
  const allPicks = getAllPicks()
  const allResults = getAllResults()
  const scores = computeSeasonScores(allPicks, allResults)

  const ranked = players
    .map(player => ({ player, data: scores[player] ?? { total: 0, races: {} } }))
    .sort((a, b) => b.data.total - a.data.total)

  const racesCompleted = RACES.filter(r => allResults[r.id]).length

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-bold text-white">Season Leaderboard</h2>
        <span className="text-xs text-f1muted">
          {racesCompleted} / {RACES.length} races complete
        </span>
      </div>
      <p className="text-f1muted text-sm mb-6">
        Click a race flag to see the per-driver score breakdown.
      </p>

      {players.length === 0 ? (
        <div className="border border-dashed border-f1border rounded p-8 text-center text-f1muted text-sm">
          Add players in the Players tab to see the leaderboard.
        </div>
      ) : (
        <div className="space-y-3">
          {ranked.map(({ player, data }, i) => (
            <PlayerRow
              key={player}
              rank={i + 1}
              player={player}
              data={data}
              allResults={allResults}
            />
          ))}
        </div>
      )}
    </div>
  )
}
