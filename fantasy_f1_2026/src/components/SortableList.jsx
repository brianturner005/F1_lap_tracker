import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable'
import DriverCard from './DriverCard'

export default function SortableList({ order, setOrder }) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  function handleDragEnd(event) {
    const { active, over } = event
    if (over && active.id !== over.id) {
      setOrder(prev => {
        const oldIdx = prev.indexOf(active.id)
        const newIdx = prev.indexOf(over.id)
        return arrayMove(prev, oldIdx, newIdx)
      })
    }
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={order} strategy={verticalListSortingStrategy}>
        <div className="space-y-1.5">
          {order.map((id, idx) => (
            <DriverCard key={id} id={id} position={idx + 1} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  )
}
