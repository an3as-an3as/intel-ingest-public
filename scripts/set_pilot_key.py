#!/usr/bin/env python3
"""Prompt for a separate pilot test key; never echo it or change app settings."""
import getpass
import os
from pathlib import Path
import sys


def save_key(path, key):
    if not key or any(c.isspace() for c in key):
        raise ValueError('The key must be nonempty and contain no spaces or line breaks.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(key)


def main():
    path = Path.home() / '.config/intel-ingest/pilot-newscatcher.key'
    if os.path.lexists(path):
        print('A pilot key file already exists. Nothing overwritten. Return to the assistant for the next step.')
        return 1
    if not sys.stdin.isatty():
        print('Run this script directly in Terminal, without piping input. Never put the key in the command.')
        return 1
    try:
        key = getpass.getpass('NewsCatcher test key (input is invisible): ').strip()
        save_key(path, key)
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled.')
        return 1
    except ValueError as error:
        print(str(error))
        return 1
    except OSError:
        print('Could not create the private key file; nothing overwritten. Report this message, not your key.')
        return 1
    print('Test key stored privately with owner-only permissions. No API requests made. Reply "ready" in chat.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
