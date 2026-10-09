// Pitch naming and guitar tuning constants (standard tuning, string 1 = high E).

const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

export function noteName(midi: number): string {
  return `${NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

const PITCH_CLASS: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

/** Parse "E4", "C#3", "Db3", "e4" or a MIDI number ("64"); null if invalid or out of 0-127. */
export function parseNoteName(text: string): number | null {
  const t = text.trim();
  if (/^\d{1,3}$/.test(t)) {
    const n = Number(t);
    return n <= 127 ? n : null;
  }
  const m = t.match(/^([A-Ga-g])([#b♯♭]?)(-?\d)$/);
  if (!m) return null;
  const acc = m[2] === '#' || m[2] === '♯' ? 1 : m[2] === 'b' || m[2] === '♭' ? -1 : 0;
  const midi = (Number(m[3]) + 1) * 12 + PITCH_CLASS[m[1].toUpperCase()] + acc;
  return midi >= 0 && midi <= 127 ? midi : null;
}

export const STRINGS: { number: number; label: string; openMidi: number }[] = [
  { number: 1, label: 'e', openMidi: 64 },
  { number: 2, label: 'B', openMidi: 59 },
  { number: 3, label: 'G', openMidi: 55 },
  { number: 4, label: 'D', openMidi: 50 },
  { number: 5, label: 'A', openMidi: 45 },
  { number: 6, label: 'E', openMidi: 40 },
];
