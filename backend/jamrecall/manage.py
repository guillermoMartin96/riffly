"""Command-line data management. Uses JAMRECALL_DATA_DIR (default: <repo>/var).

python -m jamrecall.manage where                         # print where data is stored
python -m jamrecall.manage list                          # sessions + annotation status
python -m jamrecall.manage export-session ID --out DIR   # zip: audio, reference, runs, metadata
python -m jamrecall.manage export-references --out DIR   # final annotations -> protocol JSON
python -m jamrecall.manage delete-session ID [--yes]     # permanently delete one session
python -m jamrecall.manage wipe --yes                    # permanently delete ALL data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jamrecall import annotations, datastore, store
from jamrecall.config import Settings
from jamrecall.db import migrate, transaction


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jamrecall.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where")
    sub.add_parser("list")
    e = sub.add_parser("export-session")
    e.add_argument("session_id")
    e.add_argument("--out", required=True)
    r = sub.add_parser("export-references")
    r.add_argument("--out", required=True)
    d = sub.add_parser("delete-session")
    d.add_argument("session_id")
    d.add_argument("--yes", action="store_true")
    w = sub.add_parser("wipe")
    w.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)
    settings = Settings.from_env()

    if args.cmd == "where":
        print(f"data directory: {settings.data_dir}")
        print(f"database:       {settings.db_path}")
        print(f"recordings:     {settings.media_dir / 'sessions'}/<session id>/original.*")
        return 0
    if args.cmd == "wipe":
        if not args.yes:
            print(f"This permanently deletes {settings.data_dir}. Re-run with --yes.")
            return 1
        print(f"deleted {datastore.wipe(settings)}")
        return 0
    if not settings.db_path.exists():
        print(f"no database at {settings.db_path}")
        return 1
    migrate(settings.db_path)
    with transaction(settings.db_path) as conn:
        if args.cmd == "list":
            for s in store.list_sessions(conn):
                a = annotations.get(conn, s["id"])
                ann = (
                    (
                        f"{a['status']} split={a['split']} cond={a['condition']} "
                        f"notes={len(a['notes'])} seed={a['seed'].split(':')[0]}"
                    )
                    if a
                    else "-"
                )
                print(
                    f"{s['id']}  {s['created_at']}  {s['duration_seconds']:7.2f}s  "
                    f"riffs={s['riff_count']}  annotation: {ann}"
                )
            return 0
        if args.cmd == "export-session":
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            try:
                data = datastore.export_zip(settings, conn, args.session_id)
            except KeyError:
                print(f"no session {args.session_id}")
                return 1
            path = out / f"jamrecall-{args.session_id[:8]}.zip"
            path.write_bytes(data)
            print(f"wrote {path}")
            return 0
        if args.cmd == "export-references":
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            n = 0
            for s in store.list_sessions(conn):
                a = annotations.get(conn, s["id"])
                if a is None or a["status"] != "final":
                    continue
                doc = annotations.reference_document(s, a)
                path = out / f"{a['condition']}-{a['split']}-{s['id'][:8]}.json"
                path.write_text(json.dumps(doc, indent=1))
                n += 1
                print(f"wrote {path}")
            print(f"{n} final reference annotation(s) exported (drafts are skipped)")
            return 0
        if args.cmd == "delete-session":
            s = store.get_session(conn, args.session_id)
            if s is None:
                print(f"no session {args.session_id}")
                return 1
            if not args.yes:
                print(
                    f"This permanently deletes session {args.session_id}, its recording, "
                    "riffs, transcriptions and annotation. Re-run with --yes."
                )
                return 1
            datastore.delete_session(settings, conn, args.session_id)
            print(f"deleted session {args.session_id}")
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
