import { useEffect, useRef, useState, type PointerEvent } from 'react';
import type { AnnotationNote, NoteEvent, Riff } from './api';
import { noteName, STRINGS } from './music';
import { clamp, roundMs } from './timing';

const RULER_H = 20;
const WAVE_H = 70;
const PITCH_H = 22;
const REF_H = 22;
const STRING_GAP = 16;
const REF_TOP = RULER_H + WAVE_H + PITCH_H;
const TAB_TOP = REF_TOP + REF_H + 14;
const HEIGHT = TAB_TOP + STRING_GAP * 5 + 18;
const LABEL_W = 22;

export interface Selection {
  start: number;
  end: number;
}

interface Props {
  duration: number;
  pxPerSecond: number;
  peaks: number[];
  notes: NoteEvent[];
  referenceNotes?: AnnotationNote[];
  riffs: Riff[];
  time: number;
  selection: Selection | null;
  onSelect: (s: Selection) => void;
  onSeek: (t: number) => void;
}

/**
 * One shared time axis (source-audio seconds) for waveform, detected pitches and inferred tab.
 * Drag to select a range; click to seek.
 */
export function Timeline(props: Props) {
  const { duration, pxPerSecond, peaks, notes, riffs, time, selection } = props;
  const width = Math.max(1, Math.ceil(duration * pxPerSecond));
  const x = (t: number) => LABEL_W + t * pxPerSecond;
  const scrollRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ anchor: number; moved: boolean } | null>(null);

  // Keep the playback cursor visible.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const cx = x(time);
    if (cx < el.scrollLeft || cx > el.scrollLeft + el.clientWidth - 40) {
      el.scrollLeft = Math.max(0, cx - 60);
    }
  }, [time]);

  function timeAt(e: PointerEvent<SVGSVGElement>): number {
    const rect = e.currentTarget.getBoundingClientRect();
    return roundMs(clamp((e.clientX - rect.left - LABEL_W) / pxPerSecond, 0, duration));
  }

  function onDown(e: PointerEvent<SVGSVGElement>) {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ anchor: timeAt(e), moved: false });
  }
  function onMove(e: PointerEvent<SVGSVGElement>) {
    if (!drag) return;
    const t = timeAt(e);
    if (Math.abs(t - drag.anchor) * pxPerSecond < 3 && !drag.moved) return;
    setDrag({ ...drag, moved: true });
    props.onSelect({ start: Math.min(drag.anchor, t), end: Math.max(drag.anchor, t) });
  }
  function onUp(e: PointerEvent<SVGSVGElement>) {
    if (drag && !drag.moved) props.onSeek(timeAt(e));
    setDrag(null);
  }

  const ticks: number[] = [];
  const step = pxPerSecond >= 60 ? 1 : pxPerSecond >= 20 ? 5 : 10;
  for (let t = 0; t <= duration; t += step) ticks.push(t);
  const waveMid = RULER_H + WAVE_H / 2;
  const barW = width / Math.max(1, peaks.length);

  return (
    <div className="timeline-scroll" ref={scrollRef}>
      <svg
        className="timeline"
        width={width + LABEL_W + 10}
        height={HEIGHT}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        data-testid="timeline"
        role="img"
        aria-label="Recording timeline with waveform, detected pitches and inferred tablature"
      >
        {/* ruler */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={RULER_H - 6} y2={RULER_H} className="tick" />
            <text x={x(t) + 2} y={RULER_H - 8} className="tick-label">
              {t}s
            </text>
          </g>
        ))}
        {/* waveform */}
        {peaks.map((p, i) => (
          <rect
            key={i}
            className="wave"
            x={LABEL_W + i * barW}
            width={Math.max(1, barW - 0.5)}
            y={waveMid - (p * WAVE_H) / 2}
            height={Math.max(1, p * WAVE_H)}
          />
        ))}
        {/* saved riffs */}
        {riffs.map((r) => (
          <rect
            key={r.id}
            className="riff-span"
            x={x(r.start_seconds)}
            width={(r.end_seconds - r.start_seconds) * pxPerSecond}
            y={RULER_H}
            height={HEIGHT - RULER_H}
          >
            <title>{r.title}</title>
          </rect>
        ))}
        {/* detected pitch lane */}
        <text x={2} y={RULER_H + WAVE_H + 15} className="lane-label">
          ♪
        </text>
        {notes.map((n, i) => (
          <text
            key={i}
            x={x(n.start_seconds)}
            y={RULER_H + WAVE_H + 15}
            className="pitch-label"
            data-testid="pitch-label"
          >
            {noteName(n.midi_pitch)}
          </text>
        ))}
        {/* reference annotation lane (human ground truth, separate from model output) */}
        {props.referenceNotes && props.referenceNotes.length > 0 && (
          <text x={2} y={REF_TOP + 15} className="lane-label">
            ref
          </text>
        )}
        {(props.referenceNotes ?? []).map((n, i) => (
          <g key={`ref${i}`} data-testid="ref-note">
            <rect
              className="ref-note"
              x={x(n.start_seconds)}
              y={REF_TOP + 3}
              width={Math.max(2, (n.end_seconds - n.start_seconds) * pxPerSecond)}
              height={REF_H - 6}
            />
            <text x={x(n.start_seconds) + 2} y={REF_TOP + 15} className="ref-label">
              {noteName(n.midi_pitch)}
            </text>
          </g>
        ))}
        {/* tab staff: inferred fingering */}
        {STRINGS.map((s, i) => (
          <g key={s.number}>
            <text x={4} y={TAB_TOP + i * STRING_GAP + 4} className="string-label">
              {s.label}
            </text>
            <line
              x1={LABEL_W}
              x2={LABEL_W + width}
              y1={TAB_TOP + i * STRING_GAP}
              y2={TAB_TOP + i * STRING_GAP}
              className="string-line"
            />
          </g>
        ))}
        {notes.map((n, i) =>
          n.fingering ? (
            <g key={i} data-testid="tab-note">
              <rect
                className="tab-sustain"
                x={x(n.start_seconds)}
                y={TAB_TOP + (n.fingering.string - 1) * STRING_GAP - 2}
                width={Math.max(2, (n.end_seconds - n.start_seconds) * pxPerSecond)}
                height={4}
              />
              <text
                x={x(n.start_seconds)}
                y={TAB_TOP + (n.fingering.string - 1) * STRING_GAP + 4}
                className={n.fingering.alternatives > 0 ? 'fret ambiguous' : 'fret'}
              >
                {n.fingering.fret}
                <title>
                  {noteName(n.midi_pitch)}
                  {n.confidence != null ? ` (confidence ${n.confidence.toFixed(2)})` : ''} — inferred
                  string {n.fingering.string}, fret{' '}
                  {n.fingering.fret}
                  {n.fingering.alternatives > 0
                    ? ` (${n.fingering.alternatives} other playable position${n.fingering.alternatives > 1 ? 's' : ''})`
                    : ''}
                </title>
              </text>
            </g>
          ) : (
            <text key={i} x={x(n.start_seconds)} y={HEIGHT - 2} className="fret unplayable">
              ?<title>{noteName(n.midi_pitch)} is outside the playable range in standard tuning</title>
            </text>
          ),
        )}
        {/* selection */}
        {selection && (
          <rect
            className="selection"
            data-testid="selection"
            x={x(selection.start)}
            width={Math.max(1, (selection.end - selection.start) * pxPerSecond)}
            y={RULER_H}
            height={HEIGHT - RULER_H}
          />
        )}
        {/* playback cursor */}
        <line className="cursor" x1={x(time)} x2={x(time)} y1={0} y2={HEIGHT} />
      </svg>
    </div>
  );
}
