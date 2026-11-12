import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Pause, Play, SkipBack, SkipForward } from '@phosphor-icons/react'
import { hourLabel } from '@/lib/temporal'

/** One clock, discrete computed frames. Playback never interpolates physics. */
export function TemporalPlayback({ hours, index, playing, speed, onIndex, onPlaying, onSpeed }: {
  hours: number[]; index: number; playing: boolean; speed: number
  onIndex: (index: number) => void; onPlaying: (playing: boolean) => void; onSpeed: (speed: number) => void
}) {
  const ready = hours.length > 1
  return <div className="flex flex-wrap items-center gap-2 border-t bg-muted/30 px-3 py-2" aria-label="Temporal playback">
    <Button size="icon" variant="ghost" aria-label="Previous frame" disabled={!ready || index === 0} onClick={() => { onPlaying(false); onIndex(index - 1) }}><SkipBack /></Button>
    <Button size="icon" aria-label={playing ? 'Pause replay' : 'Play replay'} disabled={!ready} onClick={() => { if (index === hours.length - 1) onIndex(0); onPlaying(!playing) }}>{playing ? <Pause weight="fill" /> : <Play weight="fill" />}</Button>
    <Button size="icon" variant="ghost" aria-label="Next frame" disabled={!ready || index === hours.length - 1} onClick={() => { onPlaying(false); onIndex(index + 1) }}><SkipForward /></Button>
    <span className="mono w-16 text-sm tabular-nums">{hourLabel(hours[index] ?? 0)}</span>
    <Slider className="min-w-24 flex-1" thumbLabels={['Simulation time']} thumbValueText={hourLabel(hours[index] ?? 0)} min={0} max={Math.max(1, hours.length - 1)} step={1} value={[index]} disabled={!ready} onValueChange={([value]) => { onPlaying(false); onIndex(value) }} />
    <span className="mono text-xs text-muted-foreground">{hourLabel(hours[hours.length - 1] ?? 0)}</span>
    <Select value={String(speed)} onValueChange={v => onSpeed(Number(v))}><SelectTrigger className="h-7 w-20" aria-label="Replay speed"><SelectValue /></SelectTrigger><SelectContent>{[1, 2, 4, 8].map(s => <SelectItem key={s} value={String(s)}>{s}×</SelectItem>)}</SelectContent></Select>
    <span className="text-xs text-muted-foreground">Offline replay · {ready ? `${index + 1}/${hours.length}` : 'No run'}</span>
  </div>
}
