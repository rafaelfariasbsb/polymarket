"""Non-blocking keyboard input for cross-platform terminal."""

from __future__ import annotations

import sys
import time
import platform

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import msvcrt
else:
    import select

from colors import Y, B, X


def read_key_nb():
    """Read key without blocking. Returns char or None."""
    if IS_WINDOWS:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            try:
                return ch.decode('utf-8').lower()
            except (UnicodeDecodeError, AttributeError):
                return None
        return None
    else:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1).lower()
        return None


def wait_for_key(timeout_sec=10):
    """Wait for key press up to timeout_sec."""
    start = time.time()
    while time.time() - start < timeout_sec:
        remaining = timeout_sec - (time.time() - start)
        sys.stdout.write(f"\r   {Y}{B}>>> S=execute U=UP D=DOWN | wait {int(remaining)}s to ignore <<<{X}  ")
        sys.stdout.flush()
        if IS_WINDOWS:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                try:
                    return ch.decode('utf-8').lower()
                except (UnicodeDecodeError, AttributeError):
                    continue
            time.sleep(0.1)
        else:
            if select.select([sys.stdin], [], [], 0.5)[0]:
                ch = sys.stdin.read(1)
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                return ch.lower()
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()
    return None


def sleep_with_key(seconds):
    """Sleep for N seconds but returns key if pressed."""
    steps = int(seconds / 0.1)
    for _ in range(steps):
        key = read_key_nb()
        if key:
            return key
        time.sleep(0.1)
    return None
