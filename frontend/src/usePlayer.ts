import { useCallback, useEffect, useRef, useState } from 'react';

export interface PlayRange {
  start: number;
  end: number;
  loop: boolean;
}

/**
 * Controls one <audio> element for a session's original recording.
 *
 * A range's end is enforced from three sources, so it holds even when the tab is in the
 * background (where animation frames are suspended):
 * - each animation frame while visible (~16 ms precision);
 * - a timer set for the expected end time (precise unless the browser throttles timers);
 * - the element's `timeupdate` events, which keep firing in background tabs (≤ ~250 ms late).
 * When the media itself ends inside a looping range (e.g. a riff ending at the recording's end,
 * where the browser's duration can be up to one Opus frame shorter than the server's), playback
 * wraps to the range start instead of stopping.
 */
export function usePlayer(src: string | null) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [range, setRange] = useState<PlayRange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rangeRef = useRef<PlayRange | null>(null);
  const timerRef = useRef<number | null>(null);
  rangeRef.current = range;

  useEffect(() => {
    setTime(0);
    setPlaying(false);
    setRange(null);
    setError(null);
  }, [src]);

  const clearTimer = () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const enforceRange = useCallback(() => {
    const a = audioRef.current;
    const r = rangeRef.current;
    if (!a || !r || a.paused) return;
    if (a.currentTime >= r.end) {
      if (r.loop) {
        a.currentTime = r.start;
      } else {
        a.pause();
        a.currentTime = r.end;
        rangeRef.current = null;
        setRange(null);
      }
    }
    scheduleEnd();
    setTime(a.currentTime);
  }, []);

  // Timer for the expected range end, rescheduled whenever the position changes.
  function scheduleEnd() {
    clearTimer();
    const a = audioRef.current;
    const r = rangeRef.current;
    if (!a || !r || a.paused) return;
    const ms = Math.max(0, ((r.end - a.currentTime) / (a.playbackRate || 1)) * 1000);
    timerRef.current = window.setTimeout(enforceRange, ms);
  }

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const a = audioRef.current;
      if (a) {
        const r = rangeRef.current;
        if (r && a.currentTime >= r.end) enforceRange();
        setTime(a.currentTime);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, enforceRange]);

  useEffect(() => clearTimer, []);

  const play = useCallback(async (r: PlayRange | null = null) => {
    const a = audioRef.current;
    if (!a) return;
    setError(null);
    rangeRef.current = r;
    setRange(r);
    if (r) a.currentTime = r.start;
    try {
      await a.play();
      scheduleEnd();
    } catch (err) {
      setError(`Playback failed: ${(err as Error).message}`);
    }
  }, []);

  const pause = useCallback(() => {
    clearTimer();
    audioRef.current?.pause();
    rangeRef.current = null;
    setRange(null);
  }, []);

  const seek = useCallback((t: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = t;
    setTime(t);
  }, []);

  const bind = {
    ref: audioRef,
    src: src ?? undefined,
    preload: 'auto' as const,
    onPlay: () => setPlaying(true),
    onPause: () => {
      clearTimer();
      setPlaying(false);
    },
    onTimeUpdate: enforceRange,
    onEnded: () => {
      const a = audioRef.current;
      const r = rangeRef.current;
      if (a && r?.loop) {
        a.currentTime = r.start;
        a.play().then(scheduleEnd, () => setPlaying(false));
        return;
      }
      clearTimer();
      setPlaying(false);
      rangeRef.current = null;
      setRange(null);
    },
    onSeeked: () => {
      setTime(audioRef.current?.currentTime ?? 0);
      scheduleEnd();
    },
    onError: () => setError('The recording could not be loaded (the audio file may be missing).'),
  };

  return { bind, time, playing, range, error, play, pause, seek };
}
