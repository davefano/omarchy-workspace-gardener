#!/usr/bin/env python3
"""Install Gardener into the current user's running Omarchy session."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

PLUGIN_ID = "io.github.davefano.gardener"
BEGIN = "  // BEGIN io.github.davefano.gardener (managed by install.py)"
END = "  // END io.github.davefano.gardener"
KEYS = {"gardener", "gardener.clean", "gardener.preview", "gardener.usage"}
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
DESKTOP = """[Desktop Entry]
Type=Application
Name=Gardener
Comment=Workspace cleanup and today's focused time
Exec=omarchy menu summon gardener
Icon=preferences-desktop-workspaces
Terminal=false
Categories=Utility;
X-Gardener-Managed=true
"""


def jsonc(text):
    """Parse JSONC without mistaking comment markers inside strings for comments."""
    clean = TOKEN.sub(lambda m: m[0] if m[0].startswith('"') else ' ' * len(m[0]), text)
    # Match strings as units so commas in quoted text are never changed.
    clean = re.sub(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',
                   lambda m: '' if m[0] == ',' else m[0], clean)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate menu key: {key}")
            result[key] = value
        return result
    value = json.loads(clean, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Menu must be a JSONC object")
    return value


def without_block(text):
    if BEGIN not in text and END not in text:
        return text
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("Ambiguous Gardener menu markers; refusing to edit")
    start = text.index(BEGIN)
    end = text.index(END, start) + len(END)
    if start == 0 or text[start - 1] != '\n' or text[end:end + 1] != '\n':
        raise ValueError("Modified Gardener menu markers; refusing to edit")
    owned = jsonc('{' + text[start:end] + '\n}')
    if set(owned) != KEYS:
        raise ValueError("Gardener menu block has unexpected entries; refusing to edit")
    # Include only the newline inserted by menu_text, retaining all original bytes.
    return text[:start - 1] + text[end + 1:]


def menu_text(original, executable, uninstall=False):
    jsonc(original)
    base = without_block(original)
    entries = jsonc(base)
    if uninstall:
        return base
    for key, entry in entries.items():
        if key == 'gardener' or key.startswith('gardener.'):
            raise ValueError(f"Existing menu entry conflicts with Gardener: {key}")
        if isinstance(entry, dict) and 'gardener' in entry.get('aliases', []):
            raise ValueError(f"Existing menu alias conflicts with Gardener: {key}")
    action = shlex.quote(str(executable))
    rows = {
        'gardener': {'label': 'Gardener', 'icon': '󰐕'},
        'gardener.clean': {'label': 'Clean workspaces', 'action': action + ' tidy --notify'},
        'gardener.preview': {'label': 'Preview cleanup', 'action': action + ' preview --notify'},
        'gardener.usage': {'label': 'Workspace usage', 'action': action + ' stats --notify'},
    }
    block = '\n' + BEGIN + '\n'
    block += ''.join('  ' + json.dumps(key) + ': ' + json.dumps(row, ensure_ascii=False) + ',\n'
                     for key, row in rows.items())
    block += END + '\n'
    # Find the object's opening brace outside comments and strings.
    masked = TOKEN.sub(lambda m: ' ' * len(m[0]), base)
    opening = masked.index('{') + 1
    result = base[:opening] + block + base[opening:]
    jsonc(result)
    return result


def exists(path):
    return path.exists() or path.is_symlink()


def check_link(path, target):
    if exists(path) and not (path.is_symlink() and path.resolve() == target.resolve()):
        raise ValueError(f"Refusing to replace unrelated path: {path}")


def read_file(path, default):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Refusing to edit non-regular file: {path}")
    return path.read_bytes().decode('utf-8') if path.exists() else default


def write_file(path, content, backup=False):
    encoded = content.encode('utf-8')
    if path.exists() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    if backup and path.exists():
        backup_path = path.with_name(path.name + f'.gardener-backup-{time.time_ns()}')
        shutil.copy2(path, backup_path)
        print(f"Backed up {path} to {backup_path}")
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(*command, timeout=15, capture_output=False):
    return subprocess.run(command, check=True, timeout=timeout,
                          capture_output=capture_output, text=True)


def wait_for_json(command, predicate, description, timeout=15):
    """IPC discovery and service loading continue after rescan/enable return."""
    deadline = time.monotonic() + timeout
    last_error = 'not ready'
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError(f"Timed out waiting for {description}: {last_error}")
        try:
            result = run(*command, timeout=min(3, remaining), capture_output=True)
            value = json.loads(result.stdout)
            if predicate(value):
                return value
            last_error = str(value.get('error') or 'not ready') if isinstance(value, dict) else 'not discovered'
        except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            last_error = str(error)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.2, remaining))


def wait_registered():
    return wait_for_json(
        ('omarchy', 'plugin', 'list', '--json'),
        lambda rows: isinstance(rows, list) and any(
            isinstance(row, dict) and row.get('id') == PLUGIN_ID for row in rows),
        'Gardener plugin discovery')


def wait_ready():
    return wait_for_json(
        ('omarchy-shell', 'gardener', 'status'),
        lambda status: isinstance(status, dict) and status.get('ready') is True
        and not status.get('error'),
        'Gardener service readiness')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true', help='Remove owned entries and links; keep usage state')
    parser.add_argument('--desktop', action='store_true', help='Also install a Gardener application launcher')
    args = parser.parse_args(argv)
    if args.uninstall and args.desktop:
        parser.error('--desktop is only used when installing')

    source = Path(__file__).resolve().parent
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    data = Path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
    plugin = config / 'omarchy/plugins' / PLUGIN_ID
    executable = home / '.local/bin/gardener'
    menu = config / 'omarchy/extensions/omarchy-menu.jsonc'
    desktop = data / 'applications' / (PLUGIN_ID + '.desktop')

    # Check every collision and parse the menu before mutating any files.
    check_link(plugin, source)
    check_link(executable, source / 'gardener.py')
    original = read_file(menu, '{}\n')
    updated = menu_text(original, executable, args.uninstall)
    if args.desktop or args.uninstall:
        desktop_content = read_file(desktop, DESKTOP)
        if desktop_content != DESKTOP:
            raise ValueError(f"Refusing to replace or remove unrelated launcher: {desktop}")
    for command in ('omarchy', 'omarchy-shell'):
        if shutil.which(command) is None:
            raise ValueError(f"Required Omarchy command is missing: {command}")

    if args.uninstall:
        if plugin.is_symlink():
            run('omarchy-shell', 'shell', 'rescanPlugins')
            wait_registered()
            run('omarchy', 'plugin', 'disable', PLUGIN_ID)
        if updated != original:
            write_file(menu, updated, backup=True)
        if desktop.exists():
            desktop.unlink()
        for link in (executable, plugin):
            if link.is_symlink():
                link.unlink()
        run('omarchy-shell', 'shell', 'rescanPlugins')
        print('Gardener uninstalled. Usage state, configuration, and menu backups were kept.')
    else:
        for filename in ('manifest.json', 'Service.qml', 'Model.js', 'gardener.py'):
            if not (source / filename).is_file():
                raise ValueError(f"Incomplete Gardener checkout: missing {filename}")
        if not os.access(source / 'gardener.py', os.X_OK):
            raise ValueError('gardener.py must be executable (chmod +x gardener.py)')
        for link, target in ((plugin, source), (executable, source / 'gardener.py')):
            if not exists(link):
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target, target_is_directory=target.is_dir())
        write_file(menu, updated, backup=True)
        if args.desktop:
            write_file(desktop, DESKTOP)
        run('omarchy-shell', 'shell', 'rescanPlugins')
        wait_registered()
        run('omarchy', 'plugin', 'enable', PLUGIN_ID)
        wait_ready()
        print('Gardener installed. Run gardener, or: omarchy menu summon gardener')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Gardener installation failed: {error}', file=sys.stderr)
        print('No unrelated files were overwritten. After resolving the error, rerun this command.', file=sys.stderr)
        sys.exit(1)
