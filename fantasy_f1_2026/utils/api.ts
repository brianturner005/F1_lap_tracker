declare const process: { env: Record<string, string | undefined> }
const BASE = (process.env['EXPO_PUBLIC_API_URL'] ?? '') + '/api'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json() as Promise<T>
}

export async function getPlayers(): Promise<string[]> {
  const data = await request<{ players: string[] }>('/players')
  return data.players
}

export async function addPlayer(name: string): Promise<string[]> {
  const data = await request<{ players: string[] }>('/players', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  return data.players
}

export async function removePlayer(name: string): Promise<string[]> {
  const data = await request<{ players: string[] }>('/players', {
    method: 'DELETE',
    body: JSON.stringify({ name }),
  })
  return data.players
}

export async function getPicksForRace(raceId: string): Promise<Record<string, string[]>> {
  const data = await request<{ picks: Record<string, string[]> }>(`/picks/${raceId}`)
  return data.picks
}

export async function savePickForRace(raceId: string, player: string, order: string[]): Promise<void> {
  await request(`/picks/${raceId}`, {
    method: 'POST',
    body: JSON.stringify({ player, order }),
  })
}

export async function getResultForRace(raceId: string): Promise<string[] | null> {
  const data = await request<{ result: string[] | null }>(`/results/${raceId}`)
  return data.result
}

export async function saveResultForRace(raceId: string, order: string[]): Promise<void> {
  await request(`/results/${raceId}`, {
    method: 'POST',
    body: JSON.stringify({ order }),
  })
}

export interface LeaderboardData {
  scores: Record<string, { total: number; races: Record<string, number> }>
  results: Record<string, string[]>
  picksByRace: Record<string, Record<string, string[]>>
}

export async function getLeaderboard(): Promise<LeaderboardData> {
  return request<LeaderboardData>('/leaderboard')
}
