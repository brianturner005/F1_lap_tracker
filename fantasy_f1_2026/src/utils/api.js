const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json()
}

export async function getPlayers() {
  const data = await request('/players')
  return data.players
}

export async function addPlayer(name) {
  const data = await request('/players', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  return data.players
}

export async function removePlayer(name) {
  const data = await request('/players', {
    method: 'DELETE',
    body: JSON.stringify({ name }),
  })
  return data.players
}

export async function getPicksForRace(raceId) {
  const data = await request(`/picks/${raceId}`)
  return data.picks
}

export async function savePickForRace(raceId, player, order) {
  await request(`/picks/${raceId}`, {
    method: 'POST',
    body: JSON.stringify({ player, order }),
  })
}

export async function getResultForRace(raceId) {
  const data = await request(`/results/${raceId}`)
  return data.result
}

export async function saveResultForRace(raceId, order) {
  await request(`/results/${raceId}`, {
    method: 'POST',
    body: JSON.stringify({ order }),
  })
}

export async function getLeaderboard() {
  return request('/leaderboard')
}
