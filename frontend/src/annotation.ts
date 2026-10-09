// Pure helpers for reference annotations (mirror the API's validation rules).
import type { AnnotationNote, NoteEvent } from './api';
import { noteName } from './music';

export const TECHNIQUES = [
  'bend',
  'slide',
  'hammer_on',
  'pull_off',
  'vibrato',
  'harmonic',
  'palm_mute',
  'other',
] as const;

export const CONDITIONS: { value: 'A' | 'B' | 'C' | 'D'; label: string }[] = [
  { value: 'A', label: 'A — clean acoustic melody' },
  { value: 'B', label: 'B — fast riff / wide leaps' },
  { value: 'C', label: 'C — clean electric' },
  { value: 'D', label: 'D — distorted electric (exploratory)' },
];

const r4 = (v: number) => Math.round(v * 10000) / 10000;

export function sortNotes(notes: AnnotationNote[]): AnnotationNote[] {
  return [...notes].sort((a, b) => a.start_seconds - b.start_seconds || a.midi_pitch - b.midi_pitch);
}

/** First problem found, or null. Same rules as the API (monophonic, inside the recording). */
export function validateNotes(notes: AnnotationNote[], duration: number): string | null {
  const sorted = sortNotes(notes);
  for (let i = 0; i < sorted.length; i++) {
    const n = sorted[i];
    const label = `Note at ${n.start_seconds.toFixed(3)} s`;
    if (!Number.isFinite(n.start_seconds) || !Number.isFinite(n.end_seconds))
      return `${label}: times must be numbers.`;
    if (n.start_seconds < 0 || n.end_seconds <= n.start_seconds)
      return `${label}: end must be after start.`;
    if (n.end_seconds > duration + 1e-6) return `${label}: ends after the recording.`;
    if (!Number.isInteger(n.midi_pitch) || n.midi_pitch < 0 || n.midi_pitch > 127)
      return `${label}: invalid pitch.`;
    const next = sorted[i + 1];
    if (next && next.start_seconds < n.end_seconds - 1e-9)
      return `${label} (${noteName(n.midi_pitch)}) overlaps the next note; reference notes must be monophonic.`;
  }
  return null;
}

export function fromTranscription(notes: NoteEvent[]): AnnotationNote[] {
  return notes.map((n) => ({
    start_seconds: r4(n.start_seconds),
    end_seconds: r4(n.end_seconds),
    midi_pitch: n.midi_pitch,
    technique: null,
  }));
}

/** A new note at `t`: ends before the next note (max 0.3 s); pitch copied from the previous note. */
export function noteAt(t: number, notes: AnnotationNote[], duration: number): AnnotationNote {
  const sorted = sortNotes(notes);
  const next = sorted.find((n) => n.start_seconds > t);
  const prev = [...sorted].reverse().find((n) => n.start_seconds <= t);
  const end = Math.min(t + 0.3, next ? next.start_seconds : duration, duration);
  return {
    start_seconds: r4(t),
    end_seconds: r4(end > t ? end : Math.min(duration, t + 0.05)),
    midi_pitch: prev?.midi_pitch ?? 64,
    technique: null,
  };
}

export function nudge(v: number, deltaSeconds: number, duration: number): number {
  return r4(Math.min(duration, Math.max(0, v + deltaSeconds)));
}

export function isEngineSeed(seed: string | undefined | null): boolean {
  return !!seed && seed.startsWith('transcription:');
}
