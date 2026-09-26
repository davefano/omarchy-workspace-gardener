#!/usr/bin/env python3
"""Workspace Gardener: on-demand commands; accounting lives in Omarchy's shell."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy/gardener"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gardener/config.json"
JOURNAL = STATE_DIR / "transaction.json"


def run(*args, timeout=8):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode or re.search(r"\b(?:error|warning):", result.stderr, re.I):
        raise RuntimeError((result.stderr or result.stdout).strip() or f"{args[0]} failed")
    return result.stdout.strip()


def hypr(query):
    return json.loads(run("hyprctl", "-j", query))


def ipc(method, *args):
    return run("omarchy-shell", "gardener", method, *args)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".gardener-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def snapshot():
    return {"instance": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""),
            "workspaces": hypr("workspaces"), "monitors": hypr("monitors"),
            "interrupted": JOURNAL.exists()}


def pinned_ids():
    if not CONFIG.exists():
        return set()
    config = json.loads(CONFIG.read_text())
    if not isinstance(config, dict):
        raise ValueError("config.json must contain an object, for example {\"pinned\": [1]}")
    value = config.get("pinned", [])
    if not isinstance(value, list) or any(type(i) is not int or not 0 < i < 2**31 for i in value):
        raise ValueError("config.json pinned must be a list of positive workspace numbers")
    return set(value)


def plan(workspaces, state, pinned=(), rules=()):
    """Reserve named, persistent, empty and rule-bound slots, including absent pins."""
    reserved = set(pinned)
    for rule in rules:
        if rule.get("enabled", True) and set(rule) - {"workspaceString", "enabled"}:
            selector = rule.get("workspaceString", "")
            if str(selector).isdigit():
                reserved.add(int(selector))
            elif not str(selector).startswith("special:"):
                raise ValueError("A workspace selector rule needs explicit handling before cleanup: " + str(selector))
    candidates = []
    for w in workspaces:
        wid = w["id"]
        if wid <= 0:
            continue
        if w.get("ispersistent") or w["name"] != str(wid) or not w["windows"]:
            reserved.add(wid)
        else:
            candidates.append(w)
    scores = state.get("seconds", {}) if state.get("day") == dt.date.today().isoformat() else {}
    candidates = [w for w in candidates if w["id"] not in reserved]
    candidates.sort(key=lambda w: (-scores.get(str(w["id"]), 0), w["id"]))
    rows, slot = [], 1
    for w in candidates:
        while slot in reserved:
            slot += 1
        rows.append({"from": w["id"], "to": slot, "seconds": scores.get(str(w["id"]), 0),
                     "windows": w["windows"], "monitor": w["monitor"]})
        slot += 1
    return rows


def renumber(source, target):
    # Values are internal integers, never window titles or untrusted Lua source.
    if any(type(i) is not int or not 0 < i < 2**31 for i in (source, target)):
        raise ValueError("Invalid workspace ID")
    run("hyprctl", "dispatch", f'hl.dsp.workspace.change_id({{workspace = "{source}", id = {target}}})')
    actual = {w["id"] for w in hypr("workspaces")}
    if target not in actual or source in actual:
        raise RuntimeError(f"Could not verify workspace {source} → {target}")
    run("hyprctl", "dispatch", f'hl.dsp.workspace.rename({{workspace = "{target}", name = "{target}"}})')


def relocate(mapping, positions, move=renumber, occupied=None):
    """Park every moving workspace first, so swaps and longer cycles cannot collide."""
    used = set(occupied or ()) | set(positions.values()) | set(mapping.values())
    scratch = max(used | {10000}) + 1
    moving = [old for old, target in mapping.items() if positions[old] != target]
    for old in moving:
        move(positions[old], scratch)
        positions[old] = scratch
        scratch += 1
    for old in moving:
        move(positions[old], mapping[old])
        positions[old] = mapping[old]


def membership(clients):
    return {c["address"]: c["workspace"]["id"] for c in clients}


def recover_positions(journal, clients):
    current = membership(clients)
    groups = {}
    for address, old in journal["members"].items():
        if address not in current:
            raise RuntimeError("Windows changed during cleanup; transaction retained for manual recovery.")
        groups.setdefault(old, set()).add(current[address])
    if any(len(ids) != 1 for ids in groups.values()):
        raise RuntimeError("Workspace groups changed; refusing to guess a recovery mapping.")
    positions = {old: next(iter(ids)) for old, ids in groups.items()}
    if len(set(positions.values())) != len(positions):
        raise RuntimeError("Workspaces were merged outside Gardener; cannot restore automatically.")
    expected = set(journal["members"])
    if any(c["address"] not in expected and c["workspace"]["id"] in positions.values() for c in clients):
        raise RuntimeError("New windows arrived during cleanup; transaction retained for manual recovery.")
    return positions


def restart_shell():
    run("omarchy", "restart", "shell", timeout=30)


def restore_transaction(journal):
    if journal["instance"] != os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        # Nothing from the old compositor can be moved in this session.
        JOURNAL.unlink()
        restart_shell()
        return
    positions = recover_positions(journal, hypr("clients"))
    relocate({old: old for old in positions}, positions, occupied=[w["id"] for w in hypr("workspaces")])
    result = ipc("restore", json.dumps(journal["state"]))
    if result != "ok":
        raise RuntimeError(result)
    JOURNAL.unlink()
    restart_shell()


def tidy():
    if JOURNAL.exists():
        raise RuntimeError("Previous cleanup was interrupted. Run gardener recover first.")
    token = uuid.uuid4().hex
    frozen = json.loads(ipc("freeze", token))
    if "error" in frozen:
        raise RuntimeError(frozen["error"])
    try:
        before = {"instance": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""), "workspaces": hypr("workspaces")}
        rows = plan(before["workspaces"], frozen["state"], pinned_ids(), hypr("workspacerules"))
        mapping = {r["from"]: r["to"] for r in rows if r["from"] != r["to"]}
        if not mapping:
            ipc("cancel", token)
            return {"message": "Workspaces are already in order.", "workspaces": rows}
        clients = hypr("clients")
        members = {a: wid for a, wid in membership(clients).items() if wid in mapping}
        if set(members.values()) != set(mapping):
            raise RuntimeError("Workspaces changed while preparing cleanup. Try again.")
        journal = {"instance": before["instance"], "state": frozen["state"], "members": members,
                   "mapping": mapping}
        atomic_json(JOURNAL, journal)
        positions = {wid: wid for wid in mapping}
        relocate(mapping, positions, occupied=[w["id"] for w in before["workspaces"]])
        actual = recover_positions(journal, hypr("clients"))
        if actual != mapping:
            raise RuntimeError("Workspace membership did not match the cleanup plan.")
        # The shell is paused during all intermediate renumbers, so counters move once.
        if ipc("finish", token, json.dumps(mapping)) != "ok":
            raise RuntimeError("Could not save usage under the new workspace numbers.")
        JOURNAL.unlink()
    except Exception:
        if JOURNAL.exists():
            try:
                restore_transaction(json.loads(JOURNAL.read_text()))
            except Exception as recovery:
                raise RuntimeError(f"Cleanup interrupted. Run gardener recover. Details: {recovery}") from recovery
        else:
            ipc("cancel", token)
        raise
    # Do not roll back successful moves if only the shell restart fails.
    try:
        restart_shell()
    except Exception as error:
        raise RuntimeError(f"Workspaces organized, but the bar needs `omarchy restart shell`: {error}") from error
    return {"message": f"Organized {len(rows)} workspaces by today's focused time.", "workspaces": rows}


def report(command):
    status = json.loads(ipc("status"))
    if not status.get("ready") or status.get("error") or status.get("frozen"):
        raise RuntimeError(status.get("error") or "Gardener is starting or cleanup is in progress.")
    workspaces = hypr("workspaces")
    if command == "preview":
        rows = plan(workspaces, status["state"], pinned_ids(), hypr("workspacerules"))
    else:
        scores = status["state"].get("seconds", {}) if status["state"]["day"] == dt.date.today().isoformat() else {}
        rows = [{"from": w["id"], "name": w["name"], "seconds": scores.get(str(w["id"]), 0),
                 "windows": w["windows"], "monitor": w["monitor"]} for w in workspaces if w["id"] > 0]
        rows.sort(key=lambda row: (-row["seconds"], row["from"]))
    return {"day": status["state"]["day"], "counting": status["counting"], "workspaces": rows,
            "message": "Preview cleanup" if command == "preview" else "Today's workspace usage"}


def format_report(result, command):
    lines = [result["message"]]
    for row in result.get("workspaces", []):
        mins = int(row["seconds"] / 60)
        duration = f"{mins // 60}h {mins % 60:02}m" if mins >= 60 else f"{mins}m"
        target = f" → {row['to']}" if command in ("preview", "tidy") else ""
        label = row.get("name", str(row["from"]))
        lines.append(f"Workspace {label}{target} · {duration} · {row['windows']} windows")
    if not result.get("workspaces"):
        lines.append("No numbered workspaces." if command == "stats" else "No eligible numbered workspaces. Named, pinned, empty and persistent slots are reserved.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="menu", choices=["menu", "stats", "preview", "tidy", "recover", "snapshot"])
    parser.add_argument("--notify", action="store_true", help="Show the result as a desktop notification")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()
    try:
        if args.command == "menu":
            run("omarchy", "menu", "summon", "gardener")
            return 0
        STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.command == "snapshot":
            print(json.dumps(snapshot()))
            return 0
        with (STATE_DIR / "command.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another Gardener command is running.")
            if args.command == "tidy":
                result = tidy()
            elif args.command == "recover":
                if not JOURNAL.exists():
                    status = json.loads(ipc("status"))
                    if not status.get("frozen"):
                        raise RuntimeError("There is no interrupted cleanup to recover.")
                    restart_shell()
                    result = {"message": "Resumed tracking and refreshed the workspace bar."}
                else:
                    restore_transaction(json.loads(JOURNAL.read_text()))
                    result = {"message": "Restored the workspace numbers from before cleanup."}
            else:
                result = report(args.command)
        message = format_report(result, args.command)
        print(json.dumps(result) if args.json else message)
        if args.notify:
            run("notify-send", "Gardener", message, timeout=3)
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        message = str(error)
        print(json.dumps({"error": message}) if args.json else f"Gardener: {message}", file=sys.stderr)
        if args.notify:
            subprocess.run(["notify-send", "-u", "critical", "Gardener", message], timeout=3, check=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
