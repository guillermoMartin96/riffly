// Pitch naming and guitar tuning constants (standard tuning, string 1 = high E).

const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

export function noteName(midi: number): string {
  return `${NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

export const STRINGS: { number: number; label: string; openMidi: number }[] = [
  { number: 1, label: 'e', openMidi: 64 },
  { number: 2, label: 'B', openMidi: 59 },
  { number: 3, label: 'G', openMidi: 55 },
  { number: 4, label: 'D', openMidi: 50 },
  { number: 5, label: 'A', openMidi: 45 },
  { number: 6, label: 'E', openMidi: 40 },
];
