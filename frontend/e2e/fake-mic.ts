// Builds the WAV that Chromium's fake capture device plays into getUserMedia.
// Default: a synthetic plucked-string phrase (Karplus-Strong). It is test input audio only;
// set JAMRECALL_FAKE_MIC_WAV to use a real recording instead.
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const SR = 48000;

function pluck(midi: number, seconds: number, seed: number): Float32Array {
  const freq = 440 * 2 ** ((midi - 69) / 12);
  const period = Math.round(SR / freq);
  const buf = new Float32Array(period);
  let s = seed;
  for (let i = 0; i < period; i++) {
    s = (s * 1103515245 + 12345) % 2147483648;
    buf[i] = (s / 2147483648) * 2 - 1;
  }
  const out = new Float32Array(Math.round(seconds * SR));
  for (let i = 0; i < out.length; i++) {
    const j = i % period;
    const next = buf[(j + 1) % period];
    out[i] = buf[j];
    buf[j] = 0.996 * 0.5 * (buf[j] + next);
  }
  return out;
}

// Pitches of the phrase below, in order (rests omitted). Used by E2E to check real transcription.
export const PHRASE_MIDI = [57, 60, 62, 64, 67, 64, 62];

export function phraseWav(): Buffer {
  // A minor pentatonic phrase with a rest, then silence padding (the fake device loops the file).
  const notes: [number, number][] = [
    [57, 0.4], [60, 0.4], [62, 0.4], [64, 0.8], [0, 0.4], [67, 0.4], [64, 0.4], [62, 0.8],
  ];
  const parts = notes.map(([m, d], i) => (m ? pluck(m, d, i + 1) : new Float32Array(d * SR)));
  parts.push(new Float32Array(SR)); // 1 s silence
  const total = parts.reduce((n, p) => n + p.length, 0);
  const pcm = Buffer.alloc(total * 2);
  let o = 0;
  for (const p of parts) for (const v of p) pcm.writeInt16LE(Math.round(Math.max(-1, Math.min(1, v * 0.6)) * 32767), (o++) * 2);
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + pcm.length, 4); h.write('WAVE', 8);
  h.write('fmt ', 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22);
  h.writeUInt32LE(SR, 24); h.writeUInt32LE(SR * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
  h.write('data', 36); h.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([h, pcm]);
}

export function fakeMicPath(): string {
  if (process.env.JAMRECALL_FAKE_MIC_WAV) return resolve(process.env.JAMRECALL_FAKE_MIC_WAV);
  const path = resolve(import.meta.dirname, '.generated', 'synthetic-phrase.wav');
  if (!existsSync(path)) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, phraseWav());
  }
  return path;
}
