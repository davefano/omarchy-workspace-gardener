# v1 verification

Validated locally on 2026-09-26 with Omarchy 4.0.3-1 and Hyprland 0.56.2.

## Automated checks

```sh
python3 -m unittest -v
node --test test_model.cjs
python3 -m py_compile gardener.py install.py
/usr/lib/qt6/bin/qmllint -I /usr/lib/qt6/qml Service.qml
omarchy plugin validate "$PWD"
```

Coverage includes ranking/ties, old-day reset, protected workspace slots,
ambiguous workspace rules, collision-free swaps and cycles, recovery membership
checks, monotonic accounting, midnight, identity remapping, compositor restart,
and asynchronous installer discovery/readiness and deadlines.

## Live checks

A separate nested Hyprland compositor and Quickshell harness were used; the
user's working workspaces were not renumbered during verification.

- Created workspaces 5, 12 and 13 with four foot windows, including a two-window
  tiled layout. Ran the real `tidy()` path against that compositor, substituting
  a restart of the isolated shell for the system's shell restart command.
- Confirmed consecutive IDs 1–3 and unchanged window addresses, grouping,
  sizes, positions, floating/fullscreen flags, monitor and focused window.
- Restarted the isolated shell and confirmed time persisted under the new IDs.
- Injected a dispatcher failure after two successful parking moves. Confirmed
  automatic rollback restored all window-to-workspace assignments and removed
  the recovery journal.
- Toggled a test lock service: counters stopped while locked and resumed after
  unlocking. Opened a special workspace: counters paused until it closed.
- Used the isolated compositor's `force_idle(120)` dispatcher: tracking paused.
  The isolated Quickshell process accumulated zero CPU ticks during a subsequent
  five-second idle sample. This is a short smoke measurement, not a battery or
  incremental memory benchmark; the process includes Qt and shell infrastructure.
- Installed the plugin and launcher entries on the real desktop, reran the
  installer successfully, and verified `gardener stats`, `gardener preview`,
  JSON output and desktop notifications. Visually inspected the native Gardener
  submenu and its three actions.

## Operational checks

`omarchy-shell gardener status` reports initialization, counting/paused state,
errors and today's counters. Normal tracking launches no recurring Python
process and checkpoints at most once per active minute, plus state boundaries.

After cleanup, verify the bar's numbers, the focused window and `gardener stats`.
If interrupted, `gardener recover` uses the local transaction journal to restore
the prior numbering; it refuses to guess if window membership changed. A shell
restart failure after a completed cleanup reports `omarchy restart shell` as the
repair. Use `python3 install.py --uninstall` to disable and remove Gardener while
retaining local usage/configuration. No network service or telemetry is involved.

Physical suspend, multiple physical monitors, and battery impact were not
measured. Suspend accounting uses Quickshell's monotonic `ElapsedTimer` and is
covered at the accounting-model boundary.

## Review

Local correctness, testing, maintainability and reliability reviews completed
with no remaining findings. The independent Claude review could not run because
the installed CLI did not support the requested model. Final automated result:
15 Python tests and 5 JavaScript tests passed; QML lint and plugin validation passed.
