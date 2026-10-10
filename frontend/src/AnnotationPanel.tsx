import { useEffect, useState } from 'react';
import {
  api,
  ApiError,
  type Annotation,
  type AnnotationFields,
  type AnnotationNote,
  type Session,
  type Transcription,
} from './api';
import {
  CONDITIONS,
  fromTranscription,
  isEngineSeed,
  noteAt,
  nudge,
  sortNotes,
  TECHNIQUES,
  validateNotes,
} from './annotation';
import { noteName, parseNoteName } from './music';

interface Props {
  session: Session;
  transcription: Transcription | null;
  playhead: number;
  onAudition: (start: number, end: number) => void;
  onNotesChange: (notes: AnnotationNote[]) => void;
}

type Row = AnnotationNote & { key: number };
let nextKey = 1;
const withKeys = (notes: AnnotationNote[]): Row[] => notes.map((n) => ({ ...n, key: nextKey++ }));
const stripKeys = (rows: Row[]): AnnotationNote[] =>
  rows.map(({ key: _key, ...n }) => n);

const EMPTY_FIELDS: AnnotationFields = {
  split: null,
  condition: null,
  method: 'manual',
  annotator: null,
  instrument: null,
  notes_text: null,
};

/**
 * Minimal reference-annotation editor. Saves to a separate store from the model output, which is
 * never modified. Times are seconds on the original recording's clock.
 */
export function AnnotationPanel({ session, transcription, playhead, onAudition, onNotesChange }: Props) {
  const [saved, setSaved] = useState<Annotation | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [fields, setFields] = useState<AnnotationFields>(EMPTY_FIELDS);
  const [seed, setSeed] = useState<string>('blank');
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<{ kind: 'error' | 'ok'; text: string } | null>(null);
  const duration = session.duration_seconds;
  const final = saved?.status === 'final';

  useEffect(() => {
    let cancelled = false;
    api
      .getAnnotation(session.id)
      .then((a) => {
        if (cancelled) return;
        setSaved(a);
        setRows(withKeys(a.notes));
        setFields({
          split: a.split, condition: a.condition, method: a.method,
          annotator: a.annotator, instrument: a.instrument, notes_text: a.notes_text,
        });
        setSeed(a.seed);
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [session.id]);

  useEffect(() => onNotesChange(rows ? stripKeys(rows) : []), [rows, onNotesChange]);

  function update(next: Row[]) {
    setRows(next);
    setDirty(true);
    setMessage(null);
  }
  function setRow(key: number, patch: Partial<AnnotationNote>) {
    update(rows!.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }
  function setField<K extends keyof AnnotationFields>(k: K, v: AnnotationFields[K]) {
    setFields({ ...fields, [k]: v });
    setDirty(true);
    setMessage(null);
  }

  function start(fromModel: boolean) {
    if (fromModel && transcription) {
      setSeed(`transcription:${transcription.id}`);
      update(withKeys(fromTranscription(transcription.notes)));
    } else {
      setSeed('blank');
      update([]);
    }
  }

  const problem = rows ? validateNotes(stripKeys(rows), duration) : null;

  async function save(): Promise<boolean> {
    if (!rows) return false;
    if (problem) {
      setMessage({ kind: 'error', text: problem });
      return false;
    }
    try {
      const a = await api.saveAnnotation(session.id, {
        ...fields,
        annotator: fields.annotator?.trim() || null,
        instrument: fields.instrument?.trim() || null,
        notes_text: fields.notes_text?.trim() || null,
        notes: sortNotes(stripKeys(rows)),
        seed: saved ? undefined : seed,
      });
      setSaved(a);
      setSeed(a.seed);
      setRows(withKeys(a.notes));
      setDirty(false);
      setMessage({ kind: 'ok', text: `Saved draft (${a.notes.length} notes).` });
      return true;
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof ApiError ? err.message : String(err) });
      return false;
    }
  }

  async function finalize() {
    if (dirty && !(await save())) return;
    try {
      const a = await api.finalizeAnnotation(session.id);
      setSaved(a);
      setMessage({ kind: 'ok', text: `Finalized as ${a.split} / condition ${a.condition}. Split is now locked.` });
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof ApiError ? err.message : String(err) });
    }
  }

  async function reopen() {
    const a = await api.reopenAnnotation(session.id);
    setSaved(a);
    setMessage({ kind: 'ok', text: `Reopened (revision ${a.revision}). The split stays locked.` });
  }

  if (!loaded) return null;

  return (
    <section className="panel annotation" aria-label="Reference annotation" data-testid="annotation-panel">
      <div className="row">
        <h3>Reference annotation</h3>
        <span className="hint">
          {saved ? `${saved.status} · revision ${saved.revision}` : rows ? 'new (unsaved)' : 'none'}
          {rows && ` · seed: ${isEngineSeed(seed) ? 'model output' : 'blank'}`}
          {dirty && ' · unsaved changes'}
        </span>
      </div>
      <p className="hint">
        Your corrected notes are stored separately; the model's transcription is never changed.
      </p>

      {!rows && (
        <div className="row-start">
          <button onClick={() => start(true)} disabled={!transcription || transcription.status !== 'succeeded'}>
            Start from model output
          </button>
          <button onClick={() => start(false)}>Start blank</button>
          <span className="hint">
            Holdout recordings must start blank (validation protocol); model-seeded references are
            fine for dev and exploratory takes.
          </span>
        </div>
      )}

      {rows && (
        <>
          {fields.split === 'holdout' && isEngineSeed(seed) && (
            <p className="error" data-testid="seed-warning">
              This reference was started from model output. Under the validation protocol it cannot
              count as an independent holdout reference; the gate will exclude it.
            </p>
          )}
          <div className="meta-grid">
            <label>
              Split
              <select
                value={fields.split ?? ''}
                disabled={final || saved?.split_locked}
                onChange={(e) => setField('split', (e.target.value || null) as AnnotationFields['split'])}
              >
                <option value="">— (exploratory)</option>
                <option value="dev">dev</option>
                <option value="holdout">holdout</option>
              </select>
            </label>
            <label>
              Condition
              <select
                value={fields.condition ?? ''}
                disabled={final}
                onChange={(e) =>
                  setField('condition', (e.target.value || null) as AnnotationFields['condition'])
                }
              >
                <option value="">—</option>
                {CONDITIONS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Method
              <select
                value={fields.method}
                disabled={final}
                onChange={(e) => setField('method', e.target.value as 'manual' | 'score')}
              >
                <option value="manual">manual (by ear + waveform)</option>
                <option value="score">score (known phrase)</option>
              </select>
            </label>
            <label>
              Annotator
              <input
                name="annotator"
                value={fields.annotator ?? ''}
                disabled={final}
                onChange={(e) => setField('annotator', e.target.value)}
              />
            </label>
            <label className="wide">
              Guitar / amp / mic setup
              <input
                name="instrument"
                value={fields.instrument ?? ''}
                disabled={final}
                placeholder="e.g. Yamaha acoustic, MacBook mic, 30 cm"
                onChange={(e) => setField('instrument', e.target.value)}
              />
            </label>
            <label className="wide">
              Notes
              <input
                name="notes_text"
                value={fields.notes_text ?? ''}
                disabled={final}
                onChange={(e) => setField('notes_text', e.target.value)}
              />
            </label>
          </div>

          <table className="note-table" data-testid="annotation-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Start (s)</th>
                <th>End (s)</th>
                <th>Pitch</th>
                <th>Technique</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.key} data-testid="annotation-row">
                  <td>{i + 1}</td>
                  <td>
                    <TimeCell
                      value={r.start_seconds}
                      disabled={final}
                      label="start"
                      onChange={(v) => setRow(r.key, { start_seconds: v })}
                      onNudge={(d) => setRow(r.key, { start_seconds: nudge(r.start_seconds, d, duration) })}
                      onPlayhead={() => setRow(r.key, { start_seconds: Math.round(playhead * 10000) / 10000 })}
                    />
                  </td>
                  <td>
                    <TimeCell
                      value={r.end_seconds}
                      disabled={final}
                      label="end"
                      onChange={(v) => setRow(r.key, { end_seconds: v })}
                      onNudge={(d) => setRow(r.key, { end_seconds: nudge(r.end_seconds, d, duration) })}
                      onPlayhead={() => setRow(r.key, { end_seconds: Math.round(playhead * 10000) / 10000 })}
                    />
                  </td>
                  <td>
                    <PitchCell
                      midi={r.midi_pitch}
                      disabled={final}
                      onChange={(m) => setRow(r.key, { midi_pitch: m })}
                    />
                  </td>
                  <td>
                    <select
                      aria-label="technique"
                      value={r.technique ?? ''}
                      disabled={final}
                      onChange={(e) => setRow(r.key, { technique: e.target.value || null })}
                    >
                      <option value="">—</option>
                      {TECHNIQUES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="actions">
                    <button
                      title="Listen to this note"
                      aria-label={`Listen to note ${i + 1}`}
                      onClick={() => onAudition(Math.max(0, r.start_seconds - 0.05), Math.min(duration, r.end_seconds + 0.05))}
                    >
                      ▶
                    </button>
                    <button
                      aria-label={`Delete note ${i + 1}`}
                      disabled={final}
                      onClick={() => update(rows.filter((x) => x.key !== r.key))}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <p className="hint">No notes yet. Move the playhead and add notes.</p>}

          <div className="row-start">
            <button
              disabled={final}
              onClick={() => update(sortRows([...rows, ...withKeys([noteAt(playhead, stripKeys(rows), duration)])]))}
            >
              + Add note at playhead ({playhead.toFixed(3)} s)
            </button>
            <button disabled={final} onClick={() => update(sortRows(rows))}>
              Sort by time
            </button>
          </div>
          {problem && (
            <p className="error" data-testid="annotation-problem">
              {problem}
            </p>
          )}
          <div className="row-start">
            <button onClick={save} disabled={final || !dirty}>
              Save draft
            </button>
            {!final && (
              <button onClick={finalize} disabled={!!problem}>
                Finalize
              </button>
            )}
            {final && <button onClick={reopen}>Reopen for edits</button>}
            <a className="button-link" href={api.exportUrl(session.id)} download data-testid="export-link">
              Export .zip
            </a>
          </div>
        </>
      )}
      {message && (
        <p role={message.kind === 'error' ? 'alert' : 'status'} className={message.kind === 'error' ? 'error' : 'ok'} data-testid="annotation-message">
          {message.text}
        </p>
      )}
    </section>
  );
}

function sortRows(rows: Row[]): Row[] {
  return [...rows].sort((a, b) => a.start_seconds - b.start_seconds || a.midi_pitch - b.midi_pitch);
}

function TimeCell(props: {
  value: number;
  disabled: boolean;
  label: string;
  onChange: (v: number) => void;
  onNudge: (delta: number) => void;
  onPlayhead: () => void;
}) {
  const [text, setText] = useState(props.value.toFixed(3));
  useEffect(() => setText(props.value.toFixed(3)), [props.value]);
  function commit() {
    const v = Number(text);
    if (Number.isFinite(v) && v >= 0) props.onChange(Math.round(v * 10000) / 10000);
    else setText(props.value.toFixed(3));
  }
  return (
    <span className="time-cell">
      <button disabled={props.disabled} aria-label={`${props.label} -10 ms`} onClick={() => props.onNudge(-0.01)}>
        −
      </button>
      <input
        aria-label={props.label}
        inputMode="decimal"
        value={text}
        disabled={props.disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      <button disabled={props.disabled} aria-label={`${props.label} +10 ms`} onClick={() => props.onNudge(0.01)}>
        +
      </button>
      <button disabled={props.disabled} title="Set to playhead" aria-label={`${props.label} at playhead`} onClick={props.onPlayhead}>
        ⌖
      </button>
    </span>
  );
}

function PitchCell(props: { midi: number; disabled: boolean; onChange: (m: number) => void }) {
  const [text, setText] = useState(noteName(props.midi));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    setText(noteName(props.midi));
    setBad(false);
  }, [props.midi]);
  function commit() {
    const m = parseNoteName(text);
    if (m === null) setBad(true);
    else props.onChange(m);
  }
  return (
    <span className="pitch-cell">
      <button disabled={props.disabled} aria-label="pitch down" onClick={() => props.onChange(Math.max(0, props.midi - 1))}>
        ♭
      </button>
      <input
        aria-label="pitch"
        className={bad ? 'invalid' : ''}
        value={text}
        disabled={props.disabled}
        onChange={(e) => {
          setText(e.target.value);
          setBad(false);
        }}
        onBlur={commit}
        onKeyDown={(e) => e.key === 'Enter' && commit()}
      />
      <button disabled={props.disabled} aria-label="pitch up" onClick={() => props.onChange(Math.min(127, props.midi + 1))}>
        ♯
      </button>
    </span>
  );
}
