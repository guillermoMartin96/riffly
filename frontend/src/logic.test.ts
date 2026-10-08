import { describe, expect, it } from 'vitest';
import { noteName } from './music';
import { describeMediaError, pickMimeType, PREFERRED_MIME_TYPES } from './recording';
import { formatTime, roundMs, validateRange } from './timing';

describe('pickMimeType', () => {
  it('prefers Opus/WebM when supported', () => {
    expect(pickMimeType(() => true)).toBe('audio/webm;codecs=opus');
  });
  it('falls back to MP4 (Safari)', () => {
    expect(pickMimeType((t) => t === 'audio/mp4')).toBe('audio/mp4');
  });
  it('returns null when nothing is supported', () => {
    expect(pickMimeType(() => false)).toBeNull();
  });
  it('only proposes containers the API accepts', () => {
    const accepted = ['audio/webm', 'audio/ogg', 'audio/mp4'];
    for (const t of PREFERRED_MIME_TYPES) expect(accepted).toContain(t.split(';')[0]);
  });
});

describe('describeMediaError', () => {
  const err = (name: string) => Object.assign(new Error('x'), { name });
  it.each([
    ['NotAllowedError', 'permission_denied'],
    ['SecurityError', 'permission_denied'],
    ['NotFoundError', 'no_device'],
    ['OverconstrainedError', 'no_device'],
    ['NotReadableError', 'device_busy'],
    ['WeirdError', 'unknown'],
  ])('%s -> %s', (name, code) => {
    expect(describeMediaError(err(name)).code).toBe(code);
  });
});

describe('timing', () => {
  it('formats times', () => {
    expect(formatTime(0)).toBe('0:00.00');
    expect(formatTime(65.256)).toBe('1:05.26');
    expect(formatTime(Infinity)).toBe('--:--.--');
  });
  it('validates ranges like the API', () => {
    expect(validateRange(0, 1, 2)).toBeNull();
    expect(validateRange(1, 2, 2)).toBeNull();
    expect(validateRange(-0.1, 1, 2)).toMatch(/at or after/);
    expect(validateRange(1, 1, 2)).toMatch(/after start/);
    expect(validateRange(1.5, 1, 2)).toMatch(/after start/);
    expect(validateRange(1, 2.5, 2)).toMatch(/at or before/);
    expect(validateRange(NaN, 1, 2)).toMatch(/numbers/);
  });
  it('rounds to milliseconds', () => {
    expect(roundMs(1.23456)).toBe(1.235);
  });
});

describe('noteName', () => {
  it('names standard-tuning open strings', () => {
    expect([40, 45, 50, 55, 59, 64].map(noteName)).toEqual(['E2', 'A2', 'D3', 'G3', 'B3', 'E4']);
  });
});
