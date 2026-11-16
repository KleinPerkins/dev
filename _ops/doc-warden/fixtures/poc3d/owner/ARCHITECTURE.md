# AWA — architecture (fixture owner)

AWA ships as ONE self-contained product — a generic KERNEL and a generic ENGINE, BOTH in
`KleinPerkins/awa`, BOTH zero-link.

The host supplies a thin **host overlay** via `AWA_POLICY` — policy literals and delegators only.

**Kernel-first:** the safety guarantee holds with the engine/daemon **OFF**.
