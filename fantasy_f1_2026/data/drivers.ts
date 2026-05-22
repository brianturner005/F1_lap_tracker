export const TEAM_COLORS: Record<string, string> = {
  'McLaren':       '#FF8000',
  'Mercedes':      '#00D2BE',
  'Red Bull':      '#3671C6',
  'Ferrari':       '#E8002D',
  'Aston Martin':  '#358C75',
  'Williams':      '#37BEDD',
  'Racing Bulls':  '#6692FF',
  'Haas':          '#B6BABD',
  'Alpine':        '#FF87BC',
  'Audi':          '#C0C0C0',
  'Cadillac':      '#FFFFFF',
}

export interface Driver {
  id: string
  name: string
  abbr: string
  team: string
}

export const DRIVERS: Driver[] = [
  { id: 'norris',     name: 'Lando Norris',     abbr: 'NOR', team: 'McLaren'      },
  { id: 'piastri',    name: 'Oscar Piastri',     abbr: 'PIA', team: 'McLaren'      },
  { id: 'russell',    name: 'George Russell',    abbr: 'RUS', team: 'Mercedes'     },
  { id: 'antonelli',  name: 'Kimi Antonelli',    abbr: 'ANT', team: 'Mercedes'     },
  { id: 'verstappen', name: 'Max Verstappen',    abbr: 'VER', team: 'Red Bull'     },
  { id: 'hadjar',     name: 'Isack Hadjar',      abbr: 'HAD', team: 'Red Bull'     },
  { id: 'leclerc',    name: 'Charles Leclerc',   abbr: 'LEC', team: 'Ferrari'      },
  { id: 'hamilton',   name: 'Lewis Hamilton',    abbr: 'HAM', team: 'Ferrari'      },
  { id: 'alonso',     name: 'Fernando Alonso',   abbr: 'ALO', team: 'Aston Martin' },
  { id: 'stroll',     name: 'Lance Stroll',      abbr: 'STR', team: 'Aston Martin' },
  { id: 'albon',      name: 'Alexander Albon',   abbr: 'ALB', team: 'Williams'     },
  { id: 'sainz',      name: 'Carlos Sainz',      abbr: 'SAI', team: 'Williams'     },
  { id: 'lawson',     name: 'Liam Lawson',       abbr: 'LAW', team: 'Racing Bulls' },
  { id: 'lindblad',   name: 'Arvid Lindblad',    abbr: 'LIN', team: 'Racing Bulls' },
  { id: 'ocon',       name: 'Esteban Ocon',      abbr: 'OCO', team: 'Haas'         },
  { id: 'bearman',    name: 'Oliver Bearman',    abbr: 'BEA', team: 'Haas'         },
  { id: 'gasly',      name: 'Pierre Gasly',      abbr: 'GAS', team: 'Alpine'       },
  { id: 'colapinto',  name: 'Franco Colapinto',  abbr: 'COL', team: 'Alpine'       },
  { id: 'hulkenberg', name: 'Nico Hulkenberg',   abbr: 'HUL', team: 'Audi'         },
  { id: 'bortoleto',  name: 'Gabriel Bortoleto', abbr: 'BOR', team: 'Audi'         },
  { id: 'perez',      name: 'Sergio Perez',      abbr: 'PER', team: 'Cadillac'     },
  { id: 'bottas',     name: 'Valtteri Bottas',   abbr: 'BOT', team: 'Cadillac'     },
]

export const DEFAULT_ORDER: string[] = DRIVERS.map(d => d.id)
