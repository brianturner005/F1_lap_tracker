const KEYS = {
  PLAYERS: 'ff1_players',
  PICKS:   'ff1_picks',
  RESULTS: 'ff1_results',
}

function load(key) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function save(key, value) {
  localStorage.setItem(key, JSON.stringify(value))
}

export function getPlayers() {
  return load(KEYS.PLAYERS) ?? []
}

export function savePlayers(players) {
  save(KEYS.PLAYERS, players)
}

// picks shape: { [raceId]: { [player]: string[] } }
export function getAllPicks() {
  return load(KEYS.PICKS) ?? {}
}

export function getPicksForRace(raceId) {
  const all = getAllPicks()
  return all[raceId] ?? {}
}

export function savePickForRace(raceId, player, order) {
  const all = getAllPicks()
  if (!all[raceId]) all[raceId] = {}
  all[raceId][player] = order
  save(KEYS.PICKS, all)
}

// results shape: { [raceId]: string[] }
export function getAllResults() {
  return load(KEYS.RESULTS) ?? {}
}

export function getResultForRace(raceId) {
  const all = getAllResults()
  return all[raceId] ?? null
}

export function saveResultForRace(raceId, order) {
  const all = getAllResults()
  all[raceId] = order
  save(KEYS.RESULTS, all)
}
