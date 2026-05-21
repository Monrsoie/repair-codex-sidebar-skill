# Repair Codex Sidebar Skill

Recover missing local Codex Desktop project conversations after restoring from `.codex_old`, switching between Windows and WSL, or repairing `state_5.sqlite`.

This repository contains a Codex skill at:

```text
skills/repair-codex-sidebar
```

## What It Fixes

Codex Desktop may show project folders in the sidebar while every project says there are no conversations. This can happen when local history exists but the app's indexes disagree across:

- `state_5.sqlite`
- `.codex-global-state.json`
- `session_index.jsonl`
- `sessions/**/*.jsonl` first-line `session_meta.cwd`

The bundled script backs up the current Codex home, merges safe user data from `.codex_old`, repairs thread metadata, normalizes Windows/WSL paths, and updates session JSONL metadata so project conversations can reappear in the sidebar.

## Install The Skill

Copy the skill folder into your Codex skills directory:

```powershell
Copy-Item -Recurse .\skills\repair-codex-sidebar "$env:USERPROFILE\.codex\skills\repair-codex-sidebar"
```

Restart Codex after installing.

## Run Manually

Close all Codex windows before repairing:

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --codex-home "$env:USERPROFILE\.codex" --old-codex-home "$env:USERPROFILE\.codex_old"
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
