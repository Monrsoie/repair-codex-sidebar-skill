# Recover Codex Sidebar Threads Skill

[中文说明](README.zh-CN.md)

Recover missing Codex Desktop sidebar threads, local project conversations, and project groups after restoring from `.codex_old`, switching between Windows and WSL, repairing `state_5.sqlite`, or rebuilding local history indexes.

This repository contains a Codex skill at:

```text
skills/repair-codex-sidebar
```

## What It Fixes

Codex Desktop may show project folders in the sidebar while every project says there are no conversations. It may also restore the threads but place them under general chats instead of their local project groups. This can happen when local history exists but the app's indexes disagree across:

- `state_5.sqlite`
- `.codex-global-state.json`
- `session_index.jsonl`
- `sessions/**/*.jsonl` first-line `session_meta.cwd`

The bundled script backs up the current Codex home, merges safe user data from `.codex_old`, repairs thread metadata, normalizes Windows/WSL paths, and updates session JSONL metadata so project conversations can reappear in the sidebar.

It also includes a lightweight v2 path for the common second-stage failure: threads already exist, but the sidebar still cannot group them under local projects because `.codex-global-state.json` has stale or wrongly typed project index fields.

## Install The Skill

Copy the skill folder into your Codex skills directory:

```powershell
Copy-Item -Recurse .\skills\repair-codex-sidebar "$env:USERPROFILE\.codex\skills\repair-codex-sidebar"
```

Restart Codex after installing.

## Run Manually

For the full repair path, close all Codex windows first:

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --codex-home "$env:USERPROFILE\.codex" --old-codex-home "$env:USERPROFILE\.codex_old"
```

If the threads are already restored but still missing from the sidebar or project groups, use the lightweight global-state repair:

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --global-state-only --codex-home "$env:USERPROFILE\.codex"
```

If the project roots themselves are missing, either pass them explicitly with `--project-root` or ask the script to include roots found in thread metadata:

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --global-state-only --include-hinted-roots
```

If Codex keeps overwriting the repaired state while it is open, run a short repair loop, fully quit Codex, wait a few seconds, and reopen it:

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --global-state-only --allow-running-codex --watch-minutes 30 --watch-interval-seconds 1
```

Diagnosis only:

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --diagnose-only
```

## Safety

The script creates a backup named like:

```text
C:\Users\<user>\.codex_sidebar_repair_backup_<timestamp>
```

It does not copy `auth.json`, `installation_id`, `cap_sid`, or `state_5.sqlite*` from `.codex_old` by default.

The lightweight repair rebuilds:

- `electron-saved-workspace-roots`
- `electron-workspace-root-labels`
- `active-workspace-roots` as an array
- `project-order`
- `projectless-thread-ids` when project-backed threads were wrongly marked projectless
