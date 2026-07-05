"""
raits/live/notify.py

Operator notification for live-trading events that require immediate attention.

Current output: a prominent boxed alert to stderr (always visible even when
stdout is redirected to a log file).

Future hook point: assign a callable to ``_PUSH_HOOK`` before starting the
live session to route alerts through email, Slack, PagerDuty, etc.

    from raits.live.notify import set_push_hook

    def my_slack_handler(level: str, message: str) -> None:
        slack_client.chat_postMessage(channel="#trading-ops", text=f"[{level}] {message}")

    set_push_hook(my_slack_handler)

The push hook is called *after* the stderr alert so a hook failure never
suppresses the console output.
"""
import sys
from typing import Callable, Optional

_PUSH_HOOK: Optional[Callable[[str, str], None]] = None


def set_push_hook(hook: Optional[Callable[[str, str], None]]) -> None:
    """Register (or clear) a push-notification callback.

    ``hook(level, message)`` is called after every ``notify()`` invocation.
    Pass ``None`` to clear a previously registered hook.
    """
    global _PUSH_HOOK
    _PUSH_HOOK = hook


def notify(level: str, message: str) -> None:
    """
    Emit a prominent operator alert and optionally forward to a push hook.

    Parameters
    ----------
    level   : Short label shown in the alert header, e.g. "TRADING HALTED"
              or "TRADING RESUMED".
    message : Human-readable detail — what happened and what to do.

    The alert is printed to *stderr* (unbuffered) so it is always visible
    even when stdout is captured or redirected.  The box format is wide
    enough to be hard to miss in a terminal scroll.
    """
    width = max(len(message) + 6, len(level) + 10, 72)
    border = "=" * width
    lines = [
        "",
        border,
        f"  [{level}]",
        f"  {message}",
        border,
        "",
    ]
    print("\n".join(lines), file=sys.stderr, flush=True)

    if _PUSH_HOOK is not None:
        try:
            _PUSH_HOOK(level, message)
        except Exception:
            pass  # hook failure must never suppress live trading
