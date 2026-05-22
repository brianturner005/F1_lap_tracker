export interface Race {
  id: string
  name: string
  country: string
  circuit: string
  date: string
  sprint?: boolean
}

export const RACES: Race[] = [
  { id: 'bahrain',        name: 'Bahrain Grand Prix',        country: '🇧🇭', circuit: 'Bahrain International Circuit',       date: '2026-03-22' },
  { id: 'saudi',          name: 'Saudi Arabian Grand Prix',  country: '🇸🇦', circuit: 'Jeddah Corniche Circuit',             date: '2026-03-29' },
  { id: 'australia',      name: 'Australian Grand Prix',     country: '🇦🇺', circuit: 'Albert Park Circuit',                 date: '2026-04-12' },
  { id: 'japan',          name: 'Japanese Grand Prix',       country: '🇯🇵', circuit: 'Suzuka Circuit',                      date: '2026-04-19' },
  { id: 'china_sprint',   name: 'Chinese Sprint',            country: '🇨🇳', circuit: 'Shanghai International Circuit',      date: '2026-04-25', sprint: true },
  { id: 'china',          name: 'Chinese Grand Prix',        country: '🇨🇳', circuit: 'Shanghai International Circuit',      date: '2026-04-26' },
  { id: 'miami_sprint',   name: 'Miami Sprint',              country: '🇺🇸', circuit: 'Miami International Autodrome',       date: '2026-05-09', sprint: true },
  { id: 'miami',          name: 'Miami Grand Prix',          country: '🇺🇸', circuit: 'Miami International Autodrome',       date: '2026-05-10' },
  { id: 'imola',          name: 'Emilia Romagna Grand Prix', country: '🇮🇹', circuit: 'Autodromo Enzo e Dino Ferrari',       date: '2026-05-24' },
  { id: 'monaco',         name: 'Monaco Grand Prix',         country: '🇲🇨', circuit: 'Circuit de Monaco',                  date: '2026-05-31' },
  { id: 'canada',         name: 'Canadian Grand Prix',       country: '🇨🇦', circuit: 'Circuit Gilles Villeneuve',           date: '2026-06-14' },
  { id: 'spain',          name: 'Spanish Grand Prix',        country: '🇪🇸', circuit: 'Circuit de Barcelona-Catalunya',      date: '2026-06-28' },
  { id: 'austria',        name: 'Austrian Grand Prix',       country: '🇦🇹', circuit: 'Red Bull Ring',                       date: '2026-07-05' },
  { id: 'britain',        name: 'British Grand Prix',        country: '🇬🇧', circuit: 'Silverstone Circuit',                 date: '2026-07-19' },
  { id: 'hungary',        name: 'Hungarian Grand Prix',      country: '🇭🇺', circuit: 'Hungaroring',                         date: '2026-08-02' },
  { id: 'belgium_sprint', name: 'Belgian Sprint',            country: '🇧🇪', circuit: 'Circuit de Spa-Francorchamps',        date: '2026-08-29', sprint: true },
  { id: 'belgium',        name: 'Belgian Grand Prix',        country: '🇧🇪', circuit: 'Circuit de Spa-Francorchamps',        date: '2026-08-30' },
  { id: 'netherlands',    name: 'Dutch Grand Prix',          country: '🇳🇱', circuit: 'Circuit Zandvoort',                   date: '2026-09-06' },
  { id: 'italy',          name: 'Italian Grand Prix',        country: '🇮🇹', circuit: 'Autodromo Nazionale Monza',           date: '2026-09-13' },
  { id: 'azerbaijan',     name: 'Azerbaijan Grand Prix',     country: '🇦🇿', circuit: 'Baku City Circuit',                   date: '2026-09-27' },
  { id: 'singapore',      name: 'Singapore Grand Prix',      country: '🇸🇬', circuit: 'Marina Bay Street Circuit',           date: '2026-10-04' },
  { id: 'usa_sprint',     name: 'United States Sprint',      country: '🇺🇸', circuit: 'Circuit of the Americas',             date: '2026-10-17', sprint: true },
  { id: 'usa',            name: 'United States Grand Prix',  country: '🇺🇸', circuit: 'Circuit of the Americas',             date: '2026-10-18' },
  { id: 'mexico',         name: 'Mexico City Grand Prix',    country: '🇲🇽', circuit: 'Autódromo Hermanos Rodríguez',        date: '2026-10-25' },
  { id: 'brazil_sprint',  name: 'São Paulo Sprint',          country: '🇧🇷', circuit: 'Autódromo José Carlos Pace',          date: '2026-11-07', sprint: true },
  { id: 'brazil',         name: 'São Paulo Grand Prix',      country: '🇧🇷', circuit: 'Autódromo José Carlos Pace',          date: '2026-11-08' },
  { id: 'lasvegas',       name: 'Las Vegas Grand Prix',      country: '🇺🇸', circuit: 'Las Vegas Strip Circuit',             date: '2026-11-21' },
  { id: 'qatar_sprint',   name: 'Qatar Sprint',              country: '🇶🇦', circuit: 'Lusail International Circuit',        date: '2026-11-28', sprint: true },
  { id: 'qatar',          name: 'Qatar Grand Prix',          country: '🇶🇦', circuit: 'Lusail International Circuit',        date: '2026-11-29' },
  { id: 'abudhabi',       name: 'Abu Dhabi Grand Prix',      country: '🇦🇪', circuit: 'Yas Marina Circuit',                  date: '2026-12-06' },
]
