import { useState } from 'react'
import { TemporalPlayback } from '@/components/TemporalPlayback'
import { Grupo } from './Primitivos'

/** Static typed frame times; the gallery never requests a computation. */
export function Temporal() {
  const [index, setIndex] = useState(1)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  return <div className="space-y-6">
    <Grupo titulo="TemporalPlayback: sem resultados"><TemporalPlayback hours={[]} index={0} playing={false} speed={1} onIndex={() => {}} onPlaying={() => {}} onSpeed={() => {}} /></Grupo>
    <Grupo titulo="TemporalPlayback: instantes discretos, sem interpolar a física"><TemporalPlayback hours={[0, 0.25, 0.5, 0.75, 1]} index={index} playing={playing} speed={speed} onIndex={setIndex} onPlaying={setPlaying} onSpeed={setSpeed} /><p className="mt-2 text-xs text-muted-foreground">Dados ilustrativos da galeria; Play mostra o estado do controle, sem executar uma simulação.</p></Grupo>
  </div>
}
