# Gardener

Gardener tracks today's focused time per workspace and tidies workspace numbers
when you ask. It runs as a headless Omarchy shell service, with a native Gardener
submenu and a small Python CLI. It never automatically reorders workspaces,
closes windows, or merges workspaces.

Requires Omarchy with shell plugins and the native JSONC menu, Hyprland workspace
`change_id` support, and Python 3. There are no additional Python dependencies or
background Python processes.

## Install

Keep this checkout in a permanent location, then run from a running Omarchy session:

```sh
python3 install.py
# Optional application launcher:
python3 install.py --desktop
```

The installer links the checkout into
`~/.config/omarchy/plugins/io.github.davefano.gardener`, links `gardener.py` as
`~/.local/bin/gardener`, and enables the service through Omarchy's plugin CLI.
Add `~/.local/bin` to your `PATH` if your shell does not already include it.

The Gardener menu contains **Clean workspaces**, **Preview cleanup**, and
**Workspace usage**. Existing menu content is preserved; changes live in a marked
block in `~/.config/omarchy/extensions/omarchy-menu.jsonc`. Each menu change makes
a timestamped backup next to that file. Installation is repeatable and refuses
conflicting links, menu entries, or application launchers. If enabling the plugin
fails, resolve the reported error and rerun the installer.

## Use

```sh
gardener                 # Open the Gardener submenu
gardener stats           # Today's focused workspace time
gardener preview         # Show the proposed cleanup
gardener tidy            # Apply cleanup
gardener recover         # Recover an interrupted cleanup transaction
gardener stats --json    # Machine-readable output
gardener preview --json
gardener tidy --json
```

`omarchy menu summon gardener` opens the same submenu. Each subcommand accepts
`--notify` to show its result as a desktop notification; the menu uses this flag.

Cleanup ranks workspaces by today's focused time, most used first, retaining
existing numeric order for ties. It changes whole workspace IDs to preserve
window layouts, monitor placement, and focus. Named, persistent, empty, and
workspace-rule-bound slots are reserved. Application rules that target a fixed
workspace number should also be protected using the pinned list below. You can
reserve additional numbers in `~/.config/gardener/config.json`:

```json
{"pinned": [1, 2]}
```

Cleanup reloads the entire Omarchy shell so its stock workspace bar reflects the
new IDs. The bar disappears briefly during that reload. If cleanup is interrupted,
run `gardener recover` before trying another cleanup.

## Time tracking

Only the focused workspace accumulates time, including on multi-monitor setups.
Tracking pauses after 120 seconds without input, regardless of idle inhibitors,
and excludes the lock screen, suspend time, and special workspaces. "Today" means
the local calendar day.

Time follows a workspace through cleanup while that workspace exists. Workspace
identity is scoped to the compositor session; restarting Hyprland resets the
session's workspace history. State is stored in
`~/.local/state/omarchy/gardener/state.json`. The service runs inside Omarchy's
existing shell process, so tracking stops while that shell is stopped.

## Development checks

Run `python3 -m unittest -v` and `node --test test_model.cjs`. See
[VERIFICATION.md](VERIFICATION.md) for live-test evidence and operational checks.

## Uninstall

```sh
python3 install.py --uninstall
```

This disables the service and removes only Gardener's matching links, marked menu
block, and optional desktop entry. Usage state, pinned-workspace configuration,
and menu backups remain. Keep the checkout at its installed location until
uninstalling; a checkout at a different location will refuse the existing links.

`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME` override their respective
default locations. The CLI link remains in `~/.local/bin`.

MIT licensed.
