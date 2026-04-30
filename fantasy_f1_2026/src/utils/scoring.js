function scoreDriver(predictedPos, actualPos) {
  const diff = Math.abs(predictedPos - actualPos)
  if (diff === 0) return 25
  if (diff === 1) return 10
  if (diff === 2) return 5
  if (diff === 3) return 2
  return 0
}

// picks and result are arrays of driver IDs in finishing order (index 0 = P1)
export function scorePickAgainstResult(picks, result) {
  if (!picks || !result || picks.length !== result.length) return 0
  return picks.reduce((total, driverId, predictedIdx) => {
    const actualIdx = result.indexOf(driverId)
    if (actualIdx === -1) return total
    return total + scoreDriver(predictedIdx, actualIdx)
  }, 0)
}

// Returns { [player]: { total, races: { [raceId]: number } } }
export function computeSeasonScores(allPicks, allResults) {
  const scores = {}

  for (const [raceId, result] of Object.entries(allResults)) {
    const racePicks = allPicks[raceId] ?? {}
    for (const [player, picks] of Object.entries(racePicks)) {
      if (!scores[player]) scores[player] = { total: 0, races: {} }
      const pts = scorePickAgainstResult(picks, result)
      scores[player].races[raceId] = pts
      scores[player].total += pts
    }
  }

  return scores
}
