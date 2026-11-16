#!/usr/bin/env python3
"""awa-dashboard-data.py — THIN DELEGATOR to the installed AWA dashboard emitter.

The dashboard status emitter now ships GENERIC (zero-link) in KleinPerkins/awa and installs to
``~/.local/share/awa/current/dashboard/emitter.py`` (bound by the global ``tools/awa`` shelf). It
emits the frozen ``awa-worktree/v1`` document, classifying every governed repo via the machine-local
policy resolver (``kernel/lib/awa_policy.py``) — resolved by role via ``AWA_POLICY`` /
``AWA_GOVERNED_ROOT``.

``~/dev`` is a THIN HOST OVERLAY: this shim keeps the historical ``_ops/bin/awa-dashboard-data.py``
path (the dashboard installer + ``make worktree-dashboard`` reference it) and forwards to the
installed emitter with the ``~/dev`` HOST POLICY OVERLAY injected, so the emitted rows reflect the
org/host literals (cpp excluded, personal/*/capabilities/*/affirm/src/* included).

DEGRADE (never fail a caller): if AWA is not installed, emit an empty-but-valid ``awa-worktree/v1``
document (the dashboard renders "no data / engine off — kernel guard active") and exit 0. The
kernel guarantee holds engine-off; a missing install is a degraded, recoverable state.

Usage: awa-dashboard-data.py [--root DIR] [--timeout SECONDS]  (args forwarded verbatim)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "awa-worktree/v1"
SELF = Path(__file__).resolve()
ROOT = SELF.parent.parent.parent  # repo root (~/dev)


def _runtime() -> Path:
    home = os.environ.get("AWA_HOME")
    if home:
        return Path(home)
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "awa" / "current"


def _degrade(reason: str) -> int:
    """Emit an empty-but-valid awa-worktree/v1 doc so the dashboard + callers never break."""
    doc = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "default_base": "main",
        "summary": {
            "repos": 0, "included": 0, "excluded": 0, "advisory": 0, "worktrees": 0,
            "linked": 0, "dirty": 0, "ahead_of_main": 0, "behind_main": 0, "diverged": 0,
            "no_base": 0, "orphan_branches": 0,
        },
        "repos": [],
        "environment": {"engine": {"running": False, "mode": "off", "reason": reason}},
        "degraded": {"reason": reason},
    }
    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str]) -> int:
    emitter = _runtime() / "dashboard" / "emitter.py"
    if not emitter.exists():
        return _degrade(f"AWA not installed at {_runtime()} — run _ops/bin/install-dev-awa-overlay.sh")

    # Inject the ~/dev host policy overlay so the installed generic emitter classifies with the
    # org/host literals (respect an explicit caller override).
    env = dict(os.environ)
    env.setdefault("AWA_POLICY", str(ROOT / "_ops" / "policy" / "worktree-policy.yml"))
    env.setdefault("AWA_GOVERNED_ROOT", str(ROOT))
    os.execve(sys.executable, [sys.executable, str(emitter), *argv[1:]], env)  # never returns


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
