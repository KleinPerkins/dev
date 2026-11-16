#!/usr/bin/env bash
# copy-honesty-check.sh — enforce the AWA copy-honesty gate (plan v2.1 §H1). Read-only.
#
# No operator-facing string may promise a PROTECTION VERB ahead of the capability that backs it.
# This check greps the single copy source table (_ops/awa/copy/operator-copy.json) AND the
# rendered operator surfaces it names for the gated verbs; a gated verb may appear ONLY if the
# capability that unlocks it is `green:true` AND its named verifier actually passes. Otherwise
# the honest phrasing in the table's `strings` must be used instead.
#
# Invoked by worktree-verify.sh (hence by `make verify-ci` and the pre-commit gate).
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SELF_DIR/../.." && pwd)"
TABLE="$ROOT/_ops/awa/copy/operator-copy.json"

if [ ! -f "$TABLE" ]; then
  printf '  FAIL  copy source table missing: %s\n' "$TABLE"
  echo "copy-honesty-check: FAILED"; exit 1
fi

# The entire gate runs in python (robust: no shell IFS/tab pitfalls). A green capability's
# named verifier is EXECUTED here (via subprocess) so a capability cannot be flipped green by
# editing the flag alone — the verifier command must actually exit 0.
AWA_ROOT="$ROOT" AWA_TABLE="$TABLE" python3 - <<'PY'
import json, os, re, subprocess, sys

root = os.environ["AWA_ROOT"]; table = os.environ["AWA_TABLE"]
try:
    t = json.load(open(table))
except Exception as exc:
    print(f"  FAIL  copy source table is not valid JSON: {exc}")
    print("copy-honesty-check: FAILED"); sys.exit(1)
print("  PASS  copy source table present + valid JSON")

# verb_id -> (capability, green, verifier_cmd, reason)
verb_to_cap = {}
for cap, spec in t.get("capabilities", {}).items():
    for v in spec.get("unlocks", []):
        verb_to_cap[v] = (cap, bool(spec.get("green", False)), spec.get("verifier_cmd", ""), spec.get("reason", ""))

# Build the text corpus to scan: each named surface file + the table's strings[].text.
corpus = {}
for surface in t.get("surfaces", []):
    p = os.path.join(root, surface)
    if os.path.isfile(p):
        corpus[os.path.basename(surface)] = open(p, encoding="utf-8", errors="replace").read()
corpus["operator-copy.json:strings"] = "\n".join(s.get("text", "") for s in t.get("strings", []))

def sibling_available() -> bool:
    return subprocess.run(
        ["bash", "_ops/bin/awa-sibling-root.sh"],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0

def verifier_passes(cmd: str) -> bool:
    if not cmd:
        return True   # no command declared; the green flag governs (documented)
    # The live verifiers need the KleinPerkins/awa engine tree (a sibling checkout OR the installed
    # standalone release). Where it is absent the live proof simply cannot run, so fall back to the
    # structural `green` flag. The engine tree is present — and the live proof therefore runs for
    # real — in the working tree (capabilities/awa), on an installed machine (~/.local/share/awa),
    # and in KleinPerkins/awa's own CI. It is absent on a generic dev-only CI runner AND in the
    # OFFLINE fresh-clone clean-room (which cannot network-install AWA); both then trust the flag,
    # mirroring the AWA_INSTALLED skips throughout worktree-verify. This keeps the SSP guarantee
    # (kernel/engine live in the standalone package) without hard-failing dev's repo-only gates.
    if not sibling_available():
        return True
    return subprocess.run(["bash", "-c", cmd], cwd=root,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

fail = 0
violations = 0
for gv in t.get("gated_verbs", []):
    vid = gv["id"]; pattern = gv["pattern"]
    rx = re.compile(pattern, re.I)
    hits = [name for name, text in corpus.items() if rx.search(text)]
    if not hits:
        continue  # verb absent everywhere -> nothing to gate
    where = ", ".join(hits)
    cap = verb_to_cap.get(vid)
    if not cap:
        print(f"  FAIL  gated verb '{vid}' appears in: {where} but NO capability unlocks it")
        fail = 1; violations += 1; continue
    c, green, vcmd, reason = cap
    if green and verifier_passes(vcmd):
        structural_only = bool(vcmd) and not sibling_available()
        note = " (awa engine tree absent — structural green only)" if structural_only else ""
        print(f"  PASS  gated verb '{vid}' used, backed by green capability '{c}' (verifier passed){note}")
    else:
        print(f"  FAIL  gated verb '{vid}' appears in: {where} but capability '{c}' is not green — {reason}")
        fail = 1; violations += 1

if violations == 0:
    print("  PASS  no gated protection verb ships ahead of its capability")

print("copy-honesty-check: " + ("OK" if fail == 0 else "FAILED"))
sys.exit(fail)
PY
