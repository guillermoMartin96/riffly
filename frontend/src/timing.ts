// Time formatting and riff-range validation (mirrors the API's rules).

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '--:--.--';
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, '0')}`;
}

export function validateRange(start: number, end: number, duration: number): string | null {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 'Start and end must be numbers.';
  if (start < 0) return 'Start must be at or after 0:00.00.';
  if (end <= start) return 'End must be after start.';
  if (end > duration + 1e-6) return `End must be at or before ${formatTime(duration)}.`;
  return null;
}

// Round to milliseconds so values typed or dragged by the user are stable across save/reload.
export function roundMs(seconds: number): number {
  return Math.round(seconds * 1000) / 1000;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}
