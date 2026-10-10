import { describe, expect, it } from 'vitest';
import { fromTranscription, isEngineSeed, noteAt, nudge, validateNotes } from './annotation';
import { noteName, parseNoteName } from './music';

const n = (s: number, e: number, m: number) => ({ start_seconds: s, end_seconds: e, midi_pitch: m, technique: null });

describe('parseNoteName', () => {
  it.each([
    ['E4', 64], ['e4', 64], ['C#3', 49], ['Db3', 49], ['B♭2', 46], ['E2', 40], ['64', 64], ['C-1', 0],
  ])('%s -> %i', (text, midi) => expect(parseNoteName(text)).toBe(midi));
  it.each(['', 'H4', 'E', '128', 'E44', 'x'])('rejects %s', (text) => expect(parseNoteName(text)).toBeNull());
  it('round-trips with noteName for the guitar range', () => {
    for (let m = 40; m <= 88; m++) expect(parseNoteName(noteName(m))).toBe(m);
  });
});

describe('validateNotes', () => {
  it('accepts monophonic notes inside the recording, in any order', () => {
    expect(validateNotes([n(1, 1.2, 60), n(0, 0.5, 62)], 2)).toBeNull();
    expect(validateNotes([n(0, 0.5, 60), n(0.5, 1, 62)], 2)).toBeNull(); // touching is fine
  });
  it('rejects overlap, reversed, beyond duration, bad pitch', () => {
    expect(validateNotes([n(0, 0.6, 60), n(0.5, 1, 62)], 2)).toMatch(/monophonic/);
    expect(validateNotes([n(1, 0.5, 60)], 2)).toMatch(/after start/);
    expect(validateNotes([n(1.5, 2.5, 60)], 2)).toMatch(/after the recording/);
    expect(validateNotes([n(0, 1, 128)], 2)).toMatch(/pitch/);
  });
});

describe('editing helpers', () => {
  it('adds a note at the playhead that stops before the next note', () => {
    expect(noteAt(1.0, [n(0.5, 0.9, 57), n(1.1, 1.5, 60)], 3)).toEqual(n(1.0, 1.1, 57));
    expect(noteAt(2.9, [], 3)).toEqual(n(2.9, 3, 64));
  });
  it('nudges within the recording', () => {
    expect(nudge(0.005, -0.01, 3)).toBe(0);
    expect(nudge(1.0, 0.01, 3)).toBe(1.01);
    expect(nudge(2.995, 0.01, 3)).toBe(3);
  });
  it('seeds from model output without copying fingering or confidence', () => {
    expect(fromTranscription([{ start_seconds: 0.123456, end_seconds: 0.5, duration_seconds: 0.38, midi_pitch: 60, confidence: 0.9, fingering: null }]))
      .toEqual([n(0.1235, 0.5, 60)]);
  });
  it('identifies engine seeds', () => {
    expect(isEngineSeed('transcription:abc:basic-pitch@0.4.0')).toBe(true);
    expect(isEngineSeed('blank')).toBe(false);
  });
});
