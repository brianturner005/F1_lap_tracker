import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { DRIVERS, TEAM_COLORS } from '../data/drivers'

export default function DriverCard({ id, position }) {
  const driver = DRIVERS.find(d => d.id === id)
  const color = TEAM_COLORS[driver?.team] ?? '#6B7280'

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="flex items-center gap-3 bg-f1card border border-f1border rounded px-3 py-2 cursor-grab active:cursor-grabbing select-none group hover:border-neutral-600 transition-colors"
    >
      <span className="text-f1muted text-xs w-6 text-right shrink-0">{position}</span>
      <div
        className="w-1 h-6 rounded-full shrink-0"
        style={{ backgroundColor: color }}
      />
      <div className="flex-1 min-w-0">
        <p className="text-white text-sm font-medium leading-none truncate">
          {driver?.name ?? id}
        </p>
        <p className="text-f1muted text-xs mt-0.5">{driver?.team}</p>
      </div>
      <span
        className="text-xs font-mono font-bold tracking-wider shrink-0"
        style={{ color }}
      >
        {driver?.abbr}
      </span>
      <span className="text-f1border group-hover:text-f1muted transition-colors text-sm">⠿</span>
    </div>
  )
}
