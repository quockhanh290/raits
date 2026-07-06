"""
global_index/notify.py
Operator notification for futures live-trading events.
Mirror of raits/live/notify.py — identical interface, independent push-hook state.

Usage:
    from global_index.notify import set_push_hook, notify

    set_push_hook(lambda level, msg: slack.post(f"[{level}] {msg}"))
"""
import sys
from typing import Callable, Optional

_PUSH_HOOK: Optional[Callable[[str, str], None]] = None


def set_push_hook(hook: Optional[Callable[[str, str], None]]) -> None:
    """Register (or clear) a push-notification callback.
    hook(level, message) is called after every notify() invocation.
    Pass None to clear a previously registered hook.
    """
    global _PUSH_HOOK
    _PUSH_HOOK = hook


def notify(level: str, message: str) -> None:
    """
    Emit a prominent boxed alert to stderr and optionally forward to a push hook.

    Parameters
    ----------
    level   : Short label shown in the alert header, e.g. "TRADING HALTED".
    message : Human-readable detail — what happened and what to do.

    Printed to stderr (unbuffered) so it is always visible even when stdout
    is captured or redirected. Hook failure never suppresses console output.
    """
    width  = max(len(message) + 6, len(level) + 10, 72)
    border = "=" * width
    lines  = ["", border, f"  [{level}]", f"  {message}", border, ""]
    print("\n".join(lines), file=sys.stderr, flush=True)
    if _PUSH_HOOK is not None:
        try:
            _PUSH_HOOK(level, message)
        except Exception:
            pass  # hook failure must never suppress live trading
