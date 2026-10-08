// Pure helpers for browser recording: container selection and error mapping.

// Preference order. Chrome/Firefox: Opus in WebM/Ogg; Safari: AAC in MP4.
export const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];

export function pickMimeType(isTypeSupported: (type: string) => boolean): string | null {
  return PREFERRED_MIME_TYPES.find((t) => isTypeSupported(t)) ?? null;
}

export type RecorderErrorCode =
  | 'unsupported'
  | 'permission_denied'
  | 'no_device'
  | 'device_busy'
  | 'insecure_context'
  | 'empty_recording'
  | 'unknown';

export interface RecorderError {
  code: RecorderErrorCode;
  message: string;
}

export function describeMediaError(err: unknown): RecorderError {
  const name = (err as { name?: string } | null)?.name;
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return {
        code: 'permission_denied',
        message:
          'Microphone access was denied. Allow microphone access for this site in your browser settings, then try again.',
      };
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return {
        code: 'no_device',
        message: 'No microphone was found. Connect an audio input device and try again.',
      };
    case 'NotReadableError':
    case 'TrackStartError':
    case 'AbortError':
      return {
        code: 'device_busy',
        message: 'The microphone could not be started. It may be in use by another application.',
      };
    default:
      return {
        code: 'unknown',
        message: `Recording failed: ${(err as Error)?.message ?? String(err)}`,
      };
  }
}

export function recordingSupport(): RecorderError | null {
  if (typeof window !== 'undefined' && window.isSecureContext === false) {
    return {
      code: 'insecure_context',
      message: 'Recording requires a secure context (https or localhost).',
    };
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    return { code: 'unsupported', message: 'This browser does not support audio recording.' };
  }
  if (!pickMimeType((t) => MediaRecorder.isTypeSupported(t))) {
    return {
      code: 'unsupported',
      message: 'This browser cannot record in a supported audio format (WebM, Ogg or MP4).',
    };
  }
  return null;
}

// Guitar needs the raw signal: browser voice processing distorts sustained notes.
export const GUITAR_AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false,
};
