#!/usr/bin/env python3
"""Repair Codex Desktop local project sidebar indexes.

This script is intentionally conservative:
- It backs up the current Codex home before writes.
- It does not copy auth or migration-sensitive state files from .codex_old.
- It repairs thread/project metadata across SQLite, global state, session index,
  and session JSONL metadata so the Desktop sidebar can rediscover local
  project conversations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


USER_DATA_DIRS = [
    "sessions",
    "archived_sessions",
    "memories",
    "rules",
    "skills",
    "plugins",
    "generated_images",
    "shell_snapshots",
    "browser",
    "pets",
    "computer-use-turn-ended",
]

USER_DATA_FILES = [
    "AGENTS.md",
    "config.toml",
    "models_cache.json",
    "transcription-history.jsonl",
    ".personality_migration",
]

SENSITIVE_OR_MIGRATION_FILES = {
    "auth.json",
    "installation_id",
    "cap_sid",
    "state_5.sqlite",
    "state_5.sqlite-wal",
    "state_5.sqlite-shm",
    "logs_2.sqlite",
    "logs_2.sqlite-wal",
    "logs_2.sqlite-shm",
}


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def default_old_codex_home(codex_home: Path) -> Path:
    return codex_home.with_name(".codex_old")


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def check_codex_not_running(allow_running: bool) -> None:
    if allow_running or os.name != "nt":
        return
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Codex.exe", "/FI", "IMAGENAME eq codex.exe"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return
    lines = [line for line in output.splitlines() if "Codex.exe" in line or "codex.exe" in line]
    if lines:
        fail(
            "Codex appears to be running. Close all Codex windows and rerun, "
            "or pass --allow-running-codex only if you are certain it is safe."
        )


def backup_codex_home(codex_home: Path, backup_root: Path | None) -> Path:
    target = backup_root or codex_home.with_name(f".codex_sidebar_repair_backup_{now_stamp()}")
    if target.exists():
        fail(f"Backup path already exists: {target}")
    ignore = shutil.ignore_patterns(".sandbox*", ".tmp", "tmp")
    shutil.copytree(codex_home, target, ignore=ignore)
    return target


def copy_overlay(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            out = dst / rel
            if item.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, out)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def merge_old_user_data(codex_home: Path, old_home: Path) -> dict[str, int]:
    stats = {"dirs": 0, "files": 0}
    if not old_home.exists():
        return stats
    for name in USER_DATA_DIRS:
        src = old_home / name
        if src.exists():
            copy_overlay(src, codex_home / name)
            stats["dirs"] += 1
    for name in USER_DATA_FILES:
        src = old_home / name
        if src.exists() and name not in SENSITIVE_OR_MIGRATION_FILES:
            copy_overlay(src, codex_home / name)
            stats["files"] += 1
    return stats


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def unique(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def to_windows_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    path = value
    if path.startswith("\\\\?\\"):
        path = path[4:]
    if path.startswith("/mnt/") and len(path) > 6 and path[5] == "/":
        drive = path[5].upper()
        rest = path[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return path


def to_extended_windows_path(value: Any) -> Any:
    path = to_windows_path(value)
    if isinstance(path, str) and len(path) >= 3 and path[1:3] == ":\\":
        return "\\\\?\\" + path
    return path


def coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def comparable_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = to_windows_path(value.strip()).replace("/", "\\")
    return path.rstrip("\\").lower()


def path_is_under(path: Any, roots: list[str]) -> bool:
    key = comparable_path(path)
    if not key:
        return False
    for root in roots:
        root_key = comparable_path(root)
        if not root_key:
            continue
        if key == root_key or key.startswith(root_key + "\\"):
            return True
    return False


def path_label(value: str) -> str:
    path = to_windows_path(value).replace("/", "\\").rstrip("\\")
    label = path.rsplit("\\", 1)[-1]
    return label or value


def normalized_unique_paths(values: list[Any]) -> list[str]:
    return unique([to_extended_windows_path(value) for value in values if isinstance(value, str) and value.strip()])


def repair_global_project_index(
    state: dict[str, Any],
    *,
    project_roots: list[str] | None = None,
    preferred_active_root: str | None = None,
    exclude_root_prefixes: list[str] | None = None,
    include_hinted_roots: bool = False,
) -> dict[str, int]:
    """Repair the lightweight sidebar/project index inside .codex-global-state.json."""

    exclude_root_prefixes = exclude_root_prefixes or []
    hints = state.get("thread-workspace-root-hints")
    if not isinstance(hints, dict):
        hints = {}

    explicit_roots = normalized_unique_paths(project_roots or [])
    saved_roots = normalized_unique_paths(coerce_string_list(state.get("electron-saved-workspace-roots")))
    order_roots = normalized_unique_paths(coerce_string_list(state.get("project-order")))
    hint_roots = normalized_unique_paths(list(hints.values()))

    if explicit_roots:
        roots = explicit_roots
    elif include_hinted_roots:
        roots = unique(saved_roots + order_roots + hint_roots)
    elif saved_roots:
        roots = saved_roots
    elif order_roots:
        roots = order_roots
    else:
        roots = hint_roots

    if exclude_root_prefixes:
        roots = [root for root in roots if not path_is_under(root, exclude_root_prefixes)]

    normalized_hints = {
        str(thread_id): to_extended_windows_path(root)
        for thread_id, root in hints.items()
        if isinstance(thread_id, str) and isinstance(root, str) and root.strip()
    }
    state["thread-workspace-root-hints"] = normalized_hints

    raw_labels = state.get("electron-workspace-root-labels")
    labels: dict[str, str] = {}
    if isinstance(raw_labels, dict):
        for key, value in raw_labels.items():
            if isinstance(key, str) and isinstance(value, str):
                labels[to_extended_windows_path(key)] = value
    for root in roots:
        labels.setdefault(root, path_label(root))

    raw_active = state.get("active-workspace-roots")
    active_before_was_list = isinstance(raw_active, list)
    active_roots = normalized_unique_paths(coerce_string_list(raw_active))
    preferred = to_extended_windows_path(preferred_active_root) if preferred_active_root else None
    if preferred and path_is_under(preferred, roots):
        active_roots = [preferred]
    else:
        active_roots = [root for root in active_roots if path_is_under(root, roots)]
        if not active_roots and roots:
            active_roots = [roots[0]]
        elif active_roots:
            active_roots = [active_roots[0]]

    existing_order = normalized_unique_paths(coerce_string_list(state.get("project-order")))
    project_order = unique(roots + existing_order)

    projectless_before = coerce_string_list(state.get("projectless-thread-ids"))
    projectless_after: list[str] = []
    removed_projectless: list[str] = []
    for thread_id in projectless_before:
        hint_root = normalized_hints.get(thread_id)
        if hint_root and path_is_under(hint_root, roots):
            removed_projectless.append(thread_id)
        else:
            projectless_after.append(thread_id)

    output_dirs = state.get("thread-projectless-output-directories")
    if isinstance(output_dirs, dict):
        for thread_id in removed_projectless:
            output_dirs.pop(thread_id, None)

    state["electron-saved-workspace-roots"] = roots
    state["electron-workspace-root-labels"] = labels
    state["active-workspace-roots"] = active_roots
    state["project-order"] = project_order
    state["projectless-thread-ids"] = unique(projectless_after)

    return {
        "project_roots": len(roots),
        "workspace_labels": len(labels),
        "active_roots": len(active_roots),
        "project_order": len(project_order),
        "projectless_before": len(projectless_before),
        "projectless_after": len(projectless_after),
        "removed_projectless": len(removed_projectless),
        "active_root_type_fixed": 0 if active_before_was_list else 1,
    }


def merge_session_index(codex_home: Path, old_home: Path | None) -> int:
    entries: dict[str, dict[str, Any]] = {}
    paths = []
    if old_home:
        paths.append(old_home / "session_index.jsonl")
    paths.append(codex_home / "session_index.jsonl")
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            thread_id = item.get("id")
            if not isinstance(thread_id, str):
                continue
            prev = entries.get(thread_id)
            if not prev or str(item.get("updated_at", "")) >= str(prev.get("updated_at", "")):
                entries[thread_id] = item
    ordered = sorted(entries.values(), key=lambda row: str(row.get("updated_at", "")))
    out = codex_home / "session_index.jsonl"
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in ordered) + "\n", encoding="utf-8")
    return len(ordered)


def merge_prompt_history(old_history: Any, cur_history: Any) -> dict[str, Any]:
    out: dict[str, Any] = dict(old_history or {}) if isinstance(old_history, dict) else {}
    if not isinstance(cur_history, dict):
        return out
    for key, value in cur_history.items():
        if isinstance(value, list) or isinstance(out.get(key), list):
            left = out.get(key) if isinstance(out.get(key), list) else []
            right = value if isinstance(value, list) else []
            out[key] = unique(left + right)
        elif isinstance(value, dict):
            old_value = out.get(key) if isinstance(out.get(key), dict) else {}
            out[key] = {**old_value, **value}
        elif key not in out:
            out[key] = value
    return out


def merge_global_state(
    codex_home: Path,
    old_home: Path | None,
    *,
    project_roots: list[str] | None = None,
    preferred_active_root: str | None = None,
    exclude_root_prefixes: list[str] | None = None,
    include_hinted_roots: bool = False,
) -> dict[str, int]:
    cur_path = codex_home / ".codex-global-state.json"
    old_path = old_home / ".codex-global-state.json" if old_home else None
    cur = read_json(cur_path, {})
    old = read_json(old_path, {}) if old_path else {}
    if not isinstance(cur, dict):
        cur = {}
    if not isinstance(old, dict):
        old = {}
    merged = dict(old)

    for key in ["projectless-thread-ids", "pinned-thread-ids"]:
        merged[key] = unique(list(old.get(key) or []) + list(cur.get(key) or []))

    merged["thread-workspace-root-hints"] = {
        **(old.get("thread-workspace-root-hints") or {}),
        **(cur.get("thread-workspace-root-hints") or {}),
    }
    merged["queued-follow-ups"] = {
        **(old.get("queued-follow-ups") or {}),
        **(cur.get("queued-follow-ups") or {}),
    }

    for key in [
        "electron-local-remote-control-installation-id",
        "electron-chrome-extension-sync-managed-plugin-ids",
    ]:
        if key in cur:
            merged[key] = cur[key]

    old_atom = old.get("electron-persisted-atom-state") or {}
    cur_atom = cur.get("electron-persisted-atom-state") or {}
    if not isinstance(old_atom, dict):
        old_atom = {}
    if not isinstance(cur_atom, dict):
        cur_atom = {}
    atom = dict(old_atom)
    atom["prompt-history"] = merge_prompt_history(old_atom.get("prompt-history"), cur_atom.get("prompt-history"))
    atom["heartbeat-thread-permissions-by-id"] = {
        **(old_atom.get("heartbeat-thread-permissions-by-id") or {}),
        **(cur_atom.get("heartbeat-thread-permissions-by-id") or {}),
    }
    merged["electron-persisted-atom-state"] = atom

    hints = merged.get("thread-workspace-root-hints") or {}
    merged["thread-workspace-root-hints"] = {
        thread_id: to_extended_windows_path(root) for thread_id, root in hints.items()
    }

    prefs = merged.get("open-in-target-preferences")
    if isinstance(prefs, dict) and isinstance(prefs.get("perPath"), dict):
        prefs["perPath"] = {to_extended_windows_path(k): v for k, v in prefs["perPath"].items()}

    perms = atom.get("heartbeat-thread-permissions-by-id")
    if isinstance(perms, dict):
        for permission in perms.values():
            try:
                roots = permission["sandboxPolicy"]["writableRoots"]
            except Exception:
                continue
            if isinstance(roots, list):
                permission["sandboxPolicy"]["writableRoots"] = unique([to_extended_windows_path(v) for v in roots])

    merged["runCodexInWindowsSubsystemForLinux"] = False
    sidebar_stats = repair_global_project_index(
        merged,
        project_roots=project_roots,
        preferred_active_root=preferred_active_root,
        exclude_root_prefixes=exclude_root_prefixes,
        include_hinted_roots=include_hinted_roots,
    )
    write_json(cur_path, merged)
    return {
        "project_roots": len(merged.get("electron-saved-workspace-roots") or []),
        "hints": len(merged.get("thread-workspace-root-hints") or {}),
        **sidebar_stats,
    }


def repair_global_state_file(
    codex_home: Path,
    *,
    project_roots: list[str] | None = None,
    preferred_active_root: str | None = None,
    exclude_root_prefixes: list[str] | None = None,
    include_hinted_roots: bool = False,
) -> dict[str, int]:
    path = codex_home / ".codex-global-state.json"
    state = read_json(path, {})
    if not isinstance(state, dict):
        state = {}
    stats = repair_global_project_index(
        state,
        project_roots=project_roots,
        preferred_active_root=preferred_active_root,
        exclude_root_prefixes=exclude_root_prefixes,
        include_hinted_roots=include_hinted_roots,
    )
    state["runCodexInWindowsSubsystemForLinux"] = False
    write_json(path, state)
    return stats


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def import_old_state_rows(codex_home: Path, old_home: Path | None) -> dict[str, int]:
    stats: dict[str, int] = {}
    if not old_home:
        return stats
    new_db = codex_home / "state_5.sqlite"
    old_db = old_home / "state_5.sqlite"
    if not new_db.exists() or not old_db.exists():
        return stats
    conn = sqlite3.connect(str(new_db))
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("ATTACH DATABASE ? AS olddb", (str(old_db),))
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM olddb.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            if table == "_sqlx_migrations":
                continue
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            old_cols = table_columns(conn, f"olddb.{table}") if False else []
            # PRAGMA does not accept database-qualified names through helpers reliably.
            old_cols = [row[1] for row in conn.execute(f"PRAGMA olddb.table_info({quote_ident(table)})")]
            new_cols = table_columns(conn, table)
            cols = [col for col in new_cols if col in old_cols]
            if not cols:
                continue
            quoted_cols = ", ".join(quote_ident(col) for col in cols)
            before = conn.total_changes
            conn.execute(
                f"INSERT OR IGNORE INTO {quote_ident(table)} ({quoted_cols}) "
                f"SELECT {quoted_cols} FROM olddb.{quote_ident(table)}"
            )
            stats[table] = conn.total_changes - before
        conn.commit()
    finally:
        conn.close()
    return stats


def normalize_state_db(codex_home: Path) -> dict[str, int]:
    db = codex_home / "state_5.sqlite"
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE threads
            SET cwd = CASE
                WHEN cwd LIKE '/mnt/c/%' THEN '\\\\?\\C:\\' || replace(substr(cwd, 8), '/', '\\')
                WHEN cwd LIKE '/mnt/d/%' THEN '\\\\?\\D:\\' || replace(substr(cwd, 8), '/', '\\')
                WHEN cwd LIKE 'C:\\%' THEN '\\\\?\\' || cwd
                WHEN cwd LIKE 'D:\\%' THEN '\\\\?\\' || cwd
                ELSE cwd
            END
            WHERE cwd LIKE '/mnt/c/%'
               OR cwd LIKE '/mnt/d/%'
               OR cwd LIKE 'C:\\%'
               OR cwd LIKE 'D:\\%'
            """
        )
        conn.execute(
            """
            UPDATE threads
            SET has_user_event = 1
            WHERE has_user_event = 0
              AND first_user_message <> ''
              AND (source = 'vscode' OR thread_source = 'user')
            """
        )
        conn.execute(
            """
            UPDATE threads
            SET thread_source = 'user'
            WHERE source = 'vscode'
              AND first_user_message <> ''
              AND (thread_source IS NULL OR thread_source = '')
            """
        )
        conn.commit()
        stats = dict(
            visible_user_threads=conn.execute(
                "SELECT count(*) FROM threads WHERE has_user_event=1"
            ).fetchone()[0],
            active_visible_user_threads=conn.execute(
                "SELECT count(*) FROM threads WHERE archived=0 AND has_user_event=1 AND source='vscode'"
            ).fetchone()[0],
            empty_thread_source=conn.execute(
                "SELECT count(*) FROM threads WHERE source='vscode' AND first_user_message <> '' "
                "AND (thread_source IS NULL OR thread_source='')"
            ).fetchone()[0],
        )
        rows = conn.execute(
            "SELECT id, cwd FROM threads WHERE archived=0 AND has_user_event=1 AND source='vscode'"
        ).fetchall()
    finally:
        conn.close()
    update_hints_from_rows(codex_home, rows)
    return stats


def update_hints_from_rows(codex_home: Path, rows: list[tuple[str, str]]) -> None:
    path = codex_home / ".codex-global-state.json"
    state = read_json(path, {})
    if not isinstance(state, dict):
        state = {}
    hints = state.get("thread-workspace-root-hints")
    if not isinstance(hints, dict):
        hints = {}
    for thread_id, cwd in rows:
        if thread_id and cwd:
            hints[thread_id] = to_extended_windows_path(cwd)
    state["thread-workspace-root-hints"] = hints
    repair_global_project_index(state)
    state["runCodexInWindowsSubsystemForLinux"] = False
    write_json(path, state)


def patch_session_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    changed = False
    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        next_cwd = to_extended_windows_path(cwd)
        if next_cwd != cwd:
            payload["cwd"] = next_cwd
            changed = True
    if payload.get("source") == "vscode" and not payload.get("thread_source"):
        payload["thread_source"] = "user"
        changed = True
    return changed


def repair_session_meta(codex_home: Path) -> dict[str, int]:
    sessions = codex_home / "sessions"
    stats = {"session_meta_checked": 0, "session_meta_changed": 0, "session_files_changed": 0}
    if not sessions.exists():
        return stats
    for file in sessions.rglob("*.jsonl"):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = text.splitlines()
        keep_newline = text.endswith("\n")
        file_changed = False
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            payload = obj.get("payload") if isinstance(obj, dict) else None
            if isinstance(obj, dict) and obj.get("type") == "session_meta":
                stats["session_meta_checked"] += 1
            if patch_session_payload(payload):
                lines[index] = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                stats["session_meta_changed"] += 1
                file_changed = True
        if file_changed:
            file.write_text("\n".join(lines) + ("\n" if keep_newline else ""), encoding="utf-8")
            stats["session_files_changed"] += 1
    return stats


def diagnose(codex_home: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    db = codex_home / "state_5.sqlite"
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            out["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            out["visible_user_threads"] = conn.execute(
                "SELECT count(*) FROM threads WHERE has_user_event=1"
            ).fetchone()[0]
            out["active_visible_user_threads"] = conn.execute(
                "SELECT count(*) FROM threads WHERE archived=0 AND has_user_event=1 AND source='vscode'"
            ).fetchone()[0]
            out["active_project_roots"] = conn.execute(
                "SELECT cwd, count(*) FROM threads WHERE archived=0 AND has_user_event=1 "
                "AND source='vscode' GROUP BY cwd ORDER BY count(*) DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
    state = read_json(codex_home / ".codex-global-state.json", {})
    if isinstance(state, dict):
        out["global_hints"] = len(state.get("thread-workspace-root-hints") or {})
        out["project_roots"] = state.get("electron-saved-workspace-roots") or []
        repaired = json.loads(json.dumps(state, ensure_ascii=False))
        out["sidebar_index_repair_preview"] = repair_global_project_index(repaired)
        active_roots = state.get("active-workspace-roots")
        out["active_workspace_roots_type"] = type(active_roots).__name__
        labels = state.get("electron-workspace-root-labels")
        out["workspace_root_labels"] = len(labels) if isinstance(labels, dict) else 0
    out.update(repair_session_meta_dry(codex_home))
    return out


def repair_session_meta_dry(codex_home: Path) -> dict[str, int]:
    sessions = codex_home / "sessions"
    stats = {"session_meta_checked": 0, "session_meta_needing_change": 0}
    if not sessions.exists():
        return stats
    for file in sessions.rglob("*.jsonl"):
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict) or obj.get("type") != "session_meta":
                continue
            stats["session_meta_checked"] += 1
            payload = obj.get("payload")
            if isinstance(payload, dict):
                cwd = payload.get("cwd")
                if isinstance(cwd, str) and to_extended_windows_path(cwd) != cwd:
                    stats["session_meta_needing_change"] += 1
                elif payload.get("source") == "vscode" and not payload.get("thread_source"):
                    stats["session_meta_needing_change"] += 1
            break
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair missing Codex Desktop local project sidebar conversations.")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--old-codex-home", type=Path, default=None)
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--skip-old-copy", action="store_true")
    parser.add_argument("--allow-running-codex", action="store_true")
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument(
        "--global-state-only",
        action="store_true",
        help="Only repair .codex-global-state.json sidebar/project indexes.",
    )
    parser.add_argument(
        "--project-root",
        action="append",
        default=[],
        help="Explicit local project root to restore. May be passed more than once.",
    )
    parser.add_argument("--preferred-active-root", default=None)
    parser.add_argument(
        "--exclude-root-prefix",
        action="append",
        default=[],
        help="Root prefix to exclude from restored local project roots. May be passed more than once.",
    )
    parser.add_argument(
        "--include-hinted-roots",
        action="store_true",
        help="Also add roots found in thread-workspace-root-hints to the restored project root list.",
    )
    parser.add_argument(
        "--watch-minutes",
        type=float,
        default=0,
        help="Repeat global-state repair for this many minutes while the user quits and reopens Codex.",
    )
    parser.add_argument("--watch-interval-seconds", type=float, default=2)
    args = parser.parse_args()

    codex_home = args.codex_home.expanduser().resolve()
    old_home = (args.old_codex_home.expanduser().resolve() if args.old_codex_home else default_old_codex_home(codex_home))

    if not codex_home.exists():
        fail(f"Codex home not found: {codex_home}")

    if args.diagnose_only:
        print(json.dumps(diagnose(codex_home), ensure_ascii=False, indent=2))
        return 0

    check_codex_not_running(args.allow_running_codex)
    backup = backup_codex_home(codex_home, args.backup_root)
    log(f"backup={backup}")

    if args.global_state_only:
        deadline = time.monotonic() + max(args.watch_minutes, 0) * 60
        while True:
            log(
                "global_state="
                + json.dumps(
                    repair_global_state_file(
                        codex_home,
                        project_roots=args.project_root,
                        preferred_active_root=args.preferred_active_root,
                        exclude_root_prefixes=args.exclude_root_prefix,
                        include_hinted_roots=args.include_hinted_roots,
                    ),
                    ensure_ascii=False,
                )
            )
            if args.watch_minutes <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(max(args.watch_interval_seconds, 0.2))
        log("diagnostics=" + json.dumps(diagnose(codex_home), ensure_ascii=False))
        log("done")
        return 0

    if not args.skip_old_copy and old_home.exists():
        log(f"copy_old_user_data={merge_old_user_data(codex_home, old_home)}")
    else:
        log("copy_old_user_data=skipped")

    log(f"session_index_entries={merge_session_index(codex_home, old_home if old_home.exists() else None)}")
    global_state_stats = merge_global_state(
        codex_home,
        old_home if old_home.exists() else None,
        project_roots=args.project_root,
        preferred_active_root=args.preferred_active_root,
        exclude_root_prefixes=args.exclude_root_prefix,
        include_hinted_roots=args.include_hinted_roots,
    )
    log(f"global_state={global_state_stats}")
    log(f"old_state_import={import_old_state_rows(codex_home, old_home if old_home.exists() else None)}")
    log(f"state_db={normalize_state_db(codex_home)}")
    log(f"session_meta={repair_session_meta(codex_home)}")
    log("diagnostics=" + json.dumps(diagnose(codex_home), ensure_ascii=False))
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
