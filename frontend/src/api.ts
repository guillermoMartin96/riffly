// Typed client for the JamRecall API. All times are seconds on the source-audio clock.

export interface Session {
  id: string;
  audio_mime: string;
  audio_bytes: number;
  audio_sha256: string;
  duration_seconds: number;
  sample_rate: number;
  created_at: string;
  status: 'ready' | 'audio_missing';
  riff_count?: number;
}

export interface Fingering {
  string: number; // 1 = high E
  fret: number;
  inferred: true;
  alternatives: number;
}

export interface NoteEvent {
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  midi_pitch: number;
  confidence: number | null;
  fingering: Fingering | null;
}

export interface Transcription {
  id: string;
  session_id: string;
  engine: string;
  engine_version: string;
  test_only: boolean;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  error: string | null;
  created_at: string;
  completed_at: string | null;
  processing_seconds: number | null;
  decode_seconds: number | null;
  inference_seconds: number | null;
  fingering_method: string | null;
  notes: NoteEvent[];
}

export interface Riff {
  id: string;
  session_id: string;
  title: string;
  start_seconds: number;
  end_seconds: number;
  created_at: string;
}

export interface AppConfig {
  transcription: {
    engine: string;
    version: string;
    test_only: boolean;
    // false until the engine passes real-recording validation (DR-0001)
    validated: boolean;
    model_load_seconds: number;
  } | null;
  accepted_mime_types: string[];
  max_upload_bytes: number;
  max_duration_seconds: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the JamRecall server');
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const code = body?.code ?? 'http_error';
    const message =
      body?.message ?? (Array.isArray(body?.detail) ? 'Invalid request' : res.statusText);
    throw new ApiError(res.status, code, message);
  }
  return body as T;
}

export const api = {
  config: () => request<AppConfig>('/api/config'),
  listSessions: () => request<Session[]>('/api/sessions'),
  getSession: (id: string) => request<Session>(`/api/sessions/${id}`),
  createSession: (blob: Blob, mime: string) => {
    const form = new FormData();
    form.append('audio', blob, 'recording');
    form.append('client_mime', mime);
    return request<Session>('/api/sessions', { method: 'POST', body: form });
  },
  audioUrl: (id: string) => `/api/sessions/${id}/audio`,
  peaks: (id: string, n: number) =>
    request<{ duration_seconds: number; peaks: number[] }>(`/api/sessions/${id}/peaks?n=${n}`),
  startTranscription: (id: string) =>
    request<Transcription>(`/api/sessions/${id}/transcriptions`, { method: 'POST' }),
  latestTranscription: (id: string) =>
    request<Transcription>(`/api/sessions/${id}/transcriptions/latest`),
  listRiffs: () => request<Riff[]>('/api/riffs'),
  sessionRiffs: (id: string) => request<Riff[]>(`/api/sessions/${id}/riffs`),
  createRiff: (sessionId: string, title: string, start: number, end: number) =>
    request<Riff>(`/api/sessions/${sessionId}/riffs`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title, start_seconds: start, end_seconds: end }),
    }),
  deleteRiff: (id: string) => request<void>(`/api/riffs/${id}`, { method: 'DELETE' }),
};
