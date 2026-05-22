import DraggableFlatList, { RenderItemParams } from 'react-native-draggable-flatlist'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { StyleSheet } from 'react-native'
import DriverCard from './DriverCard'

interface Props {
  order: string[]
  setOrder: (order: string[]) => void
}

export default function SortableList({ order, setOrder }: Props) {
  function renderItem({ item, getIndex, drag, isActive }: RenderItemParams<string>) {
    const position = (getIndex() ?? 0) + 1
    return (
      <DriverCard
        id={item}
        position={position}
        drag={drag}
        isActive={isActive}
      />
    )
  }

  return (
    <GestureHandlerRootView style={styles.root}>
      <DraggableFlatList
        data={order}
        keyExtractor={item => item}
        renderItem={renderItem}
        onDragEnd={({ data }) => setOrder(data)}
        activationDistance={10}
      />
    </GestureHandlerRootView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1 },
})
