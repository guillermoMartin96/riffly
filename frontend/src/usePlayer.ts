import { useCallback, useEffect, useRef, useState } from 'react';

export interface PlayRange {
  start: number;
  end: number;
  loop: boolean;
}

/**
 * Controls one <audio> element for a session's original recording.
 * Range playback is enforced on each animation frame: we stop (or wrap, when looping) once
 * currentTime reaches the range end, so precision is about one frame (~16 ms).
 */
export function usePlayer(src: string | null) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [range, setRange] = useState<PlayRange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rangeRef = useRef<PlayRange | null>(null);
  rangeRef.current = range;

  useEffect(() => {
    setTime(0);
    setPlaying(false);
    setRange(null);
    setError(null);
  }, [src]);

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const a = audioRef.current;
      if (a) {
        const r = rangeRef.current;
        if (r && a.currentTime >= r.end) {
          if (r.loop) {
            a.currentTime = r.start;
          } else {
            a.pause();
            a.currentTime = r.end;
            setRange(null);
          }
        }
        setTime(a.currentTime);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const play = useCallback(async (r: PlayRange | null = null) => {
    const a = audioRef.current;
    if (!a) return;
    setError(null);
    setRange(r);
    if (r) a.currentTime = r.start;
    try {
      await a.play();
    } catch (err) {
      setError(`Playback failed: ${(err as Error).message}`);
    }
  }, []);

  const pause = useCallback(() => {
    audioRef.current?.pause();
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
    onPause: () => setPlaying(false),
    onEnded: () => {
      setPlaying(false);
      setRange(null);
    },
    onSeeked: () => setTime(audioRef.current?.currentTime ?? 0),
    onError: () => setError('The recording could not be loaded (the audio file may be missing).'),
  };

  return { bind, time, playing, range, error, play, pause, seek };
}
