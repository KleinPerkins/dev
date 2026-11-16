import {
  Stack,
  Row,
  Grid,
  Spacer,
  H1,
  H2,
  H3,
  Text,
  Code,
  Stat,
  Pill,
  Table,
  Callout,
  Button,
  useHostTheme,
  useCanvasState,
  useCanvasAction,
} from "cursor/canvas";

// ---------------------------------------------------------------------------
// AWA — Agent Worktree Automation status dashboard.
//
// This file is the SOURCE-TRACKED SEED (KleinPerkins/dev). The INITIAL_RAW block
// below is data-free on purpose so the committed canvas carries no machine paths;
// `_ops/bin/install-awa-dashboard.sh` injects a live `dev-worktree.sh dashboard-data`
// snapshot between the AWA_DATA markers and writes the rendered copy into the
// Cursor workspace canvases directory (which is what the IDE compiles beside chat).
// `install-awa-dashboard.sh --check` asserts this seed stays data-free.
// ---------------------------------------------------------------------------

type WtStatus = "even" | "ahead" | "behind" | "diverged" | "no-base" | "unknown";
type Classification = "include" | "exclude" | "advisory";

type Worktree = {
  path: string;
  branch: string;
  detached: boolean;
  is_primary: boolean;
  is_linked: boolean;
  locked: boolean;
  prunable: boolean;
  head: string;
  dirty: boolean;
  dirty_count: number;
  ahead: number;
  behind: number;
  ab_status: WtStatus;
  is_base_branch: boolean;
  last_commit_ts: string | null;
  last_commit_subject: string | null;
};

type OrphanBranch = {
  branch: string;
  head: string;
  ahead: number;
  behind: number;
  ab_status: WtStatus;
  last_commit_ts: string | null;
  last_commit_subject: string | null;
};

type Repo = {
  path: string;
  rel: string;
  name: string;
  classification: Classification;
  reason: string;
  owner_repo: string;
  has_base: boolean;
  base_ref: string;
  default_base: string;
  branches: string[];
  orphan_branches: OrphanBranch[];
  worktrees: Worktree[];
};

type Summary = {
  repos: number;
  included: number;
  excluded: number;
  advisory: number;
  worktrees: number;
  linked: number;
  dirty: number;
  ahead_of_main: number;
  behind_main: number;
  diverged: number;
  no_base: number;
  orphan_branches: number;
};

// Optional, additive-only forward field (kernel-contract v1 allows additive keys). When the
// AWA engine ships it emits `environment.engine.running`; until then this is absent and the
// dashboard honestly renders the degraded "engine off — kernel guard active" state.
type Environment = {
  engine?: { running?: boolean; mode?: string; reason?: string };
};

type DashboardData = {
  schema: string;
  generated_at: string | null;
  root: string;
  default_base: string;
  summary: Summary;
  repos: Repo[];
  environment?: Environment;
};

type RefreshUi = {
  requestedAt: number;
  baselineGeneratedAt: string;
  nonce: number;
};

// ---------------------------------------------------------------------------
// Honest operator copy (mirrors _ops/awa/copy/operator-copy.json — the SINGLE copy
// source table, plan v2.1 §H1). The gated protection verbs listed in that table may NOT
// appear here until their capability's named verifier is green; _ops/checks/copy-honesty-check.sh
// greps this file and FAILS the build otherwise. Until then these honest strings state exactly
// what AWA does, without over-promising a protection the mechanism cannot yet deliver.
// ---------------------------------------------------------------------------
const HONEST = {
  invariant:
    "AWA keeps your main folder pristine for shell commands and detects native file edits there; recovery bundles and patches protect work before destructive cleanup.",
  mainFolder:
    "I keep git/install commands out of your main folder before local changes land, and I flag native file edits.",
  recovery:
    "Committed work stays on a branch; I save recovery bundles before cleanup and patches when you edit main natively — nothing gets lost.",
  concurrency:
    "Each Safe Workspace is isolated by worktree; a durable cross-surface lease is still pending (R-C).",
  degraded:
    "Engine off — your main folder is still protected for shell commands; native edits are detected.",
} as const;

// Explicit protection scope per surface — honest, capability-accurate design facts.
const SCOPES: { surface: string; state: string; detail: string }[] = [
  {
    surface: "Desktop",
    state: "shell gate + edit detection",
    detail: "beforeShellExecution asks before main-folder mutations; afterFileEdit records a detection receipt (cannot pre-block).",
  },
  {
    surface: "Cloud",
    state: "project hooks verified",
    detail:
      "Committed beforeShellExecution + afterFileEdit + beforeReadFile (L9/L10, 2026-07-05); failClosed false; PR-first for publish.",
  },
  {
    surface: "CLI",
    state: "dev-worktree verbs",
    detail: "ensure / clean (bundle-or-refuse) / status / doctor deliver the kernel guarantee with the engine off.",
  },
];

// >>> AWA_DATA_START — replaced by _ops/bin/install-awa-dashboard.sh; keep data-free in git
const INITIAL_RAW = {
  "schema": "awa-worktree/v1",
  "generated_at": null,
  "root": "",
  "default_base": "main",
  "summary": {
    "repos": 0,
    "included": 0,
    "excluded": 0,
    "advisory": 0,
    "worktrees": 0,
    "linked": 0,
    "dirty": 0,
    "ahead_of_main": 0,
    "behind_main": 0,
    "diverged": 0,
    "no_base": 0,
    "orphan_branches": 0
  },
  "repos": []
} as unknown as DashboardData;
// <<< AWA_DATA_END

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const REFRESH_COMMAND = "make worktree-dashboard";

function formatTs(iso: string | null): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t);
  const mon = MONTHS[d.getUTCMonth()];
  const day = d.getUTCDate();
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${mon} ${day} ${hh}:${mm} UTC`;
}

function snapshotAgeHours(iso: string | null): number {
  if (!iso) return Infinity;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return (Date.now() - t) / 3_600_000;
}

function ageLabel(iso: string | null): string {
  const hours = snapshotAgeHours(iso);
  if (!Number.isFinite(hours)) return "no snapshot yet";
  const mins = Math.round(hours * 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (hours < 48) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function needsAttention(wt: Worktree): boolean {
  return (
    wt.dirty ||
    wt.ahead > 0 ||
    wt.behind > 0 ||
    wt.detached ||
    wt.ab_status === "no-base" ||
    wt.ab_status === "unknown" ||
    wt.locked ||
    wt.prunable
  );
}

// Operator OUTCOME (what it means for the person), NOT raw git vocabulary (X4). The raw git
// command lives in worktreeRaw() and is only shown behind the "Show raw git" disclosure.
function worktreeOutcome(wt: Worktree): string {
  if (wt.dirty) return "Unsaved changes here — I'll keep this until it's saved.";
  if (wt.detached) return "Not on a branch — needs a branch before it's safe to tidy up.";
  if (wt.locked) return "Git is holding this workspace — needs a look before cleanup.";
  if (wt.prunable) return "Already gone on disk — safe to tidy up.";
  if (wt.ab_status === "no-base") return "Can't compare to main yet.";
  if (wt.ab_status === "diverged") return "Drifted from main — needs reconciling before it lands.";
  if (wt.ahead > 0) return "Ready to bring into main.";
  if (wt.behind > 0) return "Behind main — refresh before more work.";
  return wt.is_linked ? "Nothing to do — safe to tidy up when you're done." : "Nothing to do.";
}

function worktreeRaw(wt: Worktree): string {
  if (wt.dirty) return "git -C <path> status  # review/commit before cleanup";
  if (wt.detached) return "git -C <path> switch -c <branch>";
  if (wt.locked) return "git worktree unlock <path>  # after confirming why";
  if (wt.prunable) return "git worktree prune";
  if (wt.ab_status === "no-base") return "git fetch origin main:main";
  if (wt.ab_status === "diverged") return "git rebase main  # then push / PR";
  if (wt.ahead > 0) return "git push -u origin <branch>  # or open a PR";
  if (wt.behind > 0) return "git merge --ff-only main";
  return wt.is_linked ? "dev-worktree.sh clean --path <path>" : "dev-worktree.sh ensure";
}

function orphanAction(branch: OrphanBranch): string {
  if (branch.ab_status === "no-base") return "Fetch/create main, then decide whether to keep.";
  if (branch.ahead > 0) return "Push/open PR or delete deliberately if disposable.";
  return "Delete the local branch if it is no longer needed.";
}

function repoAction(repo: Repo): string {
  if (repo.classification === "exclude") return "AWA leaves this repo alone; use its own governance.";
  if (!repo.has_base) return "Fetch/create main so AWA can compare branches.";
  return "Use `dev-worktree.sh ensure` before mutating.";
}

function roleCell(wt: Worktree) {
  if (wt.is_linked) return <Pill size="sm" active>linked</Pill>;
  if (wt.is_primary) return <Pill size="sm">primary</Pill>;
  return <Pill size="sm">worktree</Pill>;
}

function VsMain({ wt }: { wt: Worktree }) {
  const theme = useHostTheme();
  if (wt.ab_status === "no-base") {
    return <Text size="small" tone="tertiary">no main base</Text>;
  }
  if (wt.ab_status === "unknown") {
    return <Text size="small" tone="tertiary">unknown</Text>;
  }
  if (wt.ab_status === "even") {
    return (
      <Text size="small" tone="tertiary">
        {wt.is_base_branch ? "on main" : "even"}
      </Text>
    );
  }
  const parts: string[] = [];
  if (wt.ahead > 0) parts.push(`${wt.ahead} ahead`);
  if (wt.behind > 0) parts.push(`${wt.behind} behind`);
  const color = wt.ab_status === "diverged" ? theme.accent.primary : theme.text.secondary;
  return (
    <Text size="small" weight="semibold" style={{ color }}>
      {parts.join(" · ")}
    </Text>
  );
}

function dirtyCell(wt: Worktree) {
  if (!wt.dirty) return <Text size="small" tone="quaternary">clean</Text>;
  return <Pill size="sm" active>{wt.dirty_count} dirty</Pill>;
}

function branchCell(repoRel: string, wt: Worktree) {
  return (
    <Stack gap={2}>
      <Row gap={6} align="center">
        <Code>{wt.branch || (wt.detached ? "(detached)" : "?")}</Code>
        {wt.head ? <Text size="small" tone="quaternary">{wt.head}</Text> : null}
      </Row>
      {wt.is_linked ? (
        <Text size="small" tone="quaternary">{shortWorktreePath(repoRel, wt.path)}</Text>
      ) : null}
    </Stack>
  );
}

function shortWorktreePath(repoRel: string, wtPath: string): string {
  const marker = "/.cursor/worktrees/";
  const idx = wtPath.indexOf(marker);
  if (idx >= 0) return "~" + wtPath.slice(idx);
  const parts = wtPath.split("/");
  return parts.slice(-2).join("/");
}

type WtRow = { repo: Repo; wt: Worktree };

function collectWorktrees(repos: Repo[], predicate: (r: Repo) => boolean): WtRow[] {
  const rows: WtRow[] = [];
  for (const repo of repos) {
    if (!predicate(repo)) continue;
    for (const wt of repo.worktrees) rows.push({ repo, wt });
  }
  return rows;
}

const GOVERNED_HEADERS = ["Repo", "Branch", "Role", "Working tree", "vs main", "Last commit", "Next action"];

function worktreeRows(rows: WtRow[], showRaw: boolean) {
  return rows.map(({ repo, wt }) => [
    <Stack gap={2}>
      <Text weight="semibold">{repo.rel}</Text>
      <Text size="small" tone="quaternary">{repo.owner_repo || "(no origin)"}</Text>
    </Stack>,
    branchCell(repo.rel, wt),
    roleCell(wt),
    dirtyCell(wt),
    <VsMain wt={wt} />,
    <Text size="small" tone="secondary">{formatTs(wt.last_commit_ts)}</Text>,
    <Stack gap={2}>
      <Text size="small" tone="secondary">{worktreeOutcome(wt)}</Text>
      {showRaw ? <Code>{worktreeRaw(wt)}</Code> : null}
    </Stack>,
  ]);
}

function classificationPill(cls: Classification) {
  if (cls === "include") return <Pill size="sm" active>include</Pill>;
  if (cls === "advisory") return <Pill size="sm">advisory</Pill>;
  return <Pill size="sm">exclude</Pill>;
}

function StatusCard({
  title,
  badge,
  active,
  children,
}: {
  title: string;
  badge?: string;
  active?: boolean;
  children: any;
}) {
  return (
    <Stack gap={6} style={{ padding: 14, borderRadius: 10, border: "1px solid rgba(128,128,128,0.22)" }}>
      <Row align="center" gap={8}>
        <Text weight="semibold">{title}</Text>
        <Spacer />
        {badge ? <Pill size="sm" active={!!active}>{badge}</Pill> : null}
      </Row>
      {children}
    </Stack>
  );
}

export default function AwaWorktreeDashboard() {
  const dispatch = useCanvasAction();
  const raw = INITIAL_RAW;
  const [refreshUi, setRefreshUi] = useCanvasState<RefreshUi>("awa.refreshUi", {
    requestedAt: 0,
    baselineGeneratedAt: "",
    nonce: 0,
  });
  const [showRaw, setShowRaw] = useCanvasState<boolean>("awa.showRaw", false);

  const populated = raw.repos.length > 0 && !!raw.generated_at;
  const refreshPending =
    refreshUi.requestedAt > 0 && (raw.generated_at ?? "") === refreshUi.baselineGeneratedAt;
  const refreshSucceeded =
    refreshUi.requestedAt > 0 && (raw.generated_at ?? "") !== refreshUi.baselineGeneratedAt;
  const staleSnapshot = populated && snapshotAgeHours(raw.generated_at) > 1;

  const refreshInChat = () =>
    dispatch({
      type: "newComposerChat",
      userPrompt:
        "Refresh the AWA worktree dashboard: run `make worktree-dashboard` and report the new snapshot time.",
    });
  const onRefresh = () => {
    setRefreshUi({
      requestedAt: Date.now(),
      baselineGeneratedAt: raw.generated_at ?? "",
      nonce: refreshUi.nonce + 1,
    });
    refreshInChat();
  };
  const onDismissRefresh = () => {
    setRefreshUi({ requestedAt: 0, baselineGeneratedAt: "", nonce: refreshUi.nonce });
  };

  const governed = raw.repos.filter((r) => r.classification !== "exclude");
  const excluded = raw.repos.filter((r) => r.classification === "exclude");
  const attention = collectWorktrees(governed, () => true).filter((row) => needsAttention(row.wt));
  const steady = collectWorktrees(governed, () => true).filter((row) => !needsAttention(row.wt));
  const orphanRows = governed.flatMap((repo) => repo.orphan_branches.map((branch) => ({ repo, branch })));
  const hasAttention = attention.length > 0;

  // Honest promise-state derivation (plan §H1/§H6). Everything below is either a static
  // capability truth (the engine is unbuilt today) or derived from the read-only summary —
  // never a claim the mechanism cannot back.
  const engineInfo = raw.environment?.engine;
  const engineRunning = engineInfo?.running ?? false;
  const includedPrimaries = collectWorktrees(governed, () => true).filter((r) => !r.wt.is_linked);
  const mainEdited = includedPrimaries.some((r) => r.wt.dirty);
  const preservedCount =
    collectWorktrees(governed, () => true).filter((r) => r.wt.ahead > 0).length +
    orphanRows.filter((o) => o.branch.ahead > 0).length;
  const isolatedCount = raw.summary.linked;

  return (
    <Stack gap={20} style={{ padding: 24, maxWidth: 1120 }}>
      <Stack gap={4}>
        <Row align="center">
          <H1>AWA — worktree status vs main</H1>
          <Spacer />
          <Button variant="secondary" onClick={() => setShowRaw(!showRaw)}>
            {showRaw ? "Hide raw git" : "Show raw git"}
          </Button>
          <Button variant="secondary" disabled={refreshPending} onClick={onRefresh}>
            {refreshPending ? "Agent refresh requested" : "Refresh via agent"}
          </Button>
          <Pill active={!hasAttention}>{hasAttention ? "needs attention" : "all clean"}</Pill>
        </Row>
        <Text tone="secondary">
          Safe-Workspace state for every governed repo under <Code>~/dev</Code>: worktrees, branches,
          and how each stands against <Code>main</Code>.
        </Text>
        <Text size="small" tone="tertiary">{HONEST.invariant}</Text>
        <Text size="small" tone="tertiary">
          Source: <Code>dev-worktree.sh dashboard-data</Code>
          {populated ? (
            <>
              {" "}· snapshot {formatTs(raw.generated_at)} ({ageLabel(raw.generated_at)})
              {refreshUi.nonce > 0 ? <> · refresh #{refreshUi.nonce}</> : null}
            </>
          ) : null}
        </Text>
      </Stack>

      {!populated ? (
        <Callout tone="info" title="No snapshot yet">
          This is the data-free seed. Populate the live dashboard by running{" "}
          <Code>{REFRESH_COMMAND}</Code> from <Code>~/dev</Code> — it runs the read-only emitter and
          rewrites this canvas in your Cursor workspace with real worktree status.
        </Callout>
      ) : null}

      {refreshPending ? (
        <Callout tone="info" title="Agent refresh requested">
          This canvas cannot execute shell directly. An agent/chat must run <Code>{REFRESH_COMMAND}</Code>;
          this view updates after the rendered canvas is regenerated with a newer snapshot.
          <Row gap={8} wrap style={{ marginTop: 8 }}>
            <Button variant="secondary" onClick={refreshInChat}>Run make worktree-dashboard</Button>
            <Button variant="secondary" onClick={onDismissRefresh}>Cancel</Button>
          </Row>
        </Callout>
      ) : null}

      {refreshSucceeded ? (
        <Callout tone="success" title="Snapshot updated">
          Now showing {formatTs(raw.generated_at)}.
          <Row gap={8} wrap style={{ marginTop: 8 }}>
            <Button variant="secondary" onClick={onDismissRefresh}>Dismiss</Button>
          </Row>
        </Callout>
      ) : null}

      <Stack gap={8}>
        <H2>Protection state</H2>
        <Grid columns="repeat(auto-fit, minmax(240px, 1fr))" gap={12}>
          <StatusCard title="Main folder" badge={mainEdited ? "edits detected" : "shell-gated"} active={!mainEdited}>
            <Text size="small" tone="secondary">{HONEST.mainFolder}</Text>
          </StatusCard>
          <StatusCard title="Work preservation" badge={`${preservedCount} on a branch`} active={preservedCount > 0}>
            <Text size="small" tone="secondary">{HONEST.recovery}</Text>
          </StatusCard>
          <StatusCard title="Concurrency" badge={`${isolatedCount} isolated`} active>
            <Text size="small" tone="secondary">{HONEST.concurrency}</Text>
          </StatusCard>
        </Grid>
        <Grid columns="repeat(auto-fit, minmax(240px, 1fr))" gap={12}>
          <StatusCard title="Engine" badge={engineRunning ? "running" : "engine off — kernel guard active"} active={engineRunning}>
            <Text size="small" tone="secondary">
              {engineInfo?.reason ?? (engineRunning ? "AWA engine is running (observation + bookkeeping)." : HONEST.degraded)}
            </Text>
          </StatusCard>
          <StatusCard
            title="Snapshot"
            badge={staleSnapshot ? "stale" : populated ? "fresh" : "no data"}
            active={!staleSnapshot && populated}
          >
            <Text size="small" tone="secondary">
              {populated
                ? `Data ${ageLabel(raw.generated_at)} — run ${REFRESH_COMMAND} for current state.`
                : "Run make worktree-dashboard to populate this view."}
            </Text>
          </StatusCard>
        </Grid>
        <Grid columns="repeat(auto-fit, minmax(240px, 1fr))" gap={12}>
          {SCOPES.map((s) => (
            <StatusCard key={s.surface} title={`Scope · ${s.surface}`} badge={s.state}>
              <Text size="small" tone="secondary">{s.detail}</Text>
            </StatusCard>
          ))}
        </Grid>
      </Stack>

      {populated ? (
        <Grid columns="repeat(auto-fit, minmax(124px, 1fr))" gap={12}>
          <Stat value={raw.summary.repos} label="Governed repos" />
          <Stat value={raw.summary.included} label="Included" tone="info" />
          <Stat value={raw.summary.worktrees} label="Worktrees" />
          <Stat value={raw.summary.linked} label="Linked" tone={raw.summary.linked ? "info" : "success"} />
          <Stat value={raw.summary.dirty} label="Dirty" tone={raw.summary.dirty ? "warning" : "success"} />
          <Stat value={raw.summary.ahead_of_main} label="Ahead of main" tone={raw.summary.ahead_of_main ? "warning" : "success"} />
          <Stat value={raw.summary.behind_main} label="Behind main" tone={raw.summary.behind_main ? "warning" : "success"} />
          <Stat value={raw.summary.orphan_branches} label="Orphan AWA branches" tone={raw.summary.orphan_branches ? "warning" : "success"} />
        </Grid>
      ) : null}

      {hasAttention ? (
        <Stack gap={8}>
          <Row align="center" gap={8}>
            <H2>Needs attention</H2>
            <Pill size="sm" active>{attention.length}</Pill>
          </Row>
          <Text size="small" tone="tertiary">
            Worktrees that are dirty, ahead/behind <Code>main</Code>, detached, or locked/prunable.
          </Text>
          <Table
            headers={GOVERNED_HEADERS}
            rows={worktreeRows(attention, showRaw)}
            rowTone={attention.map(() => "warning" as const)}
            striped
          />
        </Stack>
      ) : null}

      {steady.length > 0 ? (
        <Stack gap={8}>
          <H2>Tracking main</H2>
          <Table
            headers={GOVERNED_HEADERS}
            rows={worktreeRows(steady, showRaw)}
            rowTone={steady.map(() => "success" as const)}
            striped
          />
          <Text size="small" tone="tertiary">
            "vs main" = <Code>git rev-list --left-right --count &lt;base&gt;...HEAD</Code> per worktree,
            base = local <Code>main</Code> then <Code>origin/main</Code>. Read-only.
          </Text>
        </Stack>
      ) : null}

      {orphanRows.length > 0 ? (
        <Stack gap={8}>
          <Row align="center" gap={8}>
            <H2>Orphan AWA branches</H2>
            <Pill size="sm" active>{orphanRows.length}</Pill>
          </Row>
          <Text size="small" tone="tertiary">
            Local <Code>cursor/worktree/*</Code> branches not currently attached to any worktree.
          </Text>
          <Table
            headers={["Repo", "Branch", "vs main", "Last commit", "Next action"]}
            rows={orphanRows.map(({ repo, branch }) => [
              <Text weight="semibold">{repo.rel}</Text>,
              <Row gap={6} align="center">
                <Code>{branch.branch}</Code>
                {branch.head ? <Text size="small" tone="quaternary">{branch.head}</Text> : null}
              </Row>,
              <Text size="small" tone="secondary">
                {branch.ab_status === "even"
                  ? "even"
                  : branch.ab_status === "no-base"
                    ? "no main base"
                    : `${branch.ahead} ahead · ${branch.behind} behind`}
              </Text>,
              <Text size="small" tone="secondary">{formatTs(branch.last_commit_ts)}</Text>,
              <Text size="small" tone="secondary">{orphanAction(branch)}</Text>,
            ])}
            rowTone={orphanRows.map(() => "warning" as const)}
            striped
          />
        </Stack>
      ) : null}

      {excluded.length > 0 ? (
        <Stack gap={8}>
          <H3>Excluded from automation</H3>
          <Text size="small" tone="tertiary">
            Governed by policy but not worktree-automated (AWA leaves these alone).
          </Text>
          <Table
            headers={["Repo", "Reason", "Current branch", "Next action"]}
            rows={excluded.map((r) => [
              <Stack gap={2}>
                <Row gap={6} align="center">
                  <Text weight="semibold">{r.rel === "." ? "~/dev (umbrella)" : r.rel}</Text>
                  {classificationPill(r.classification)}
                </Row>
                <Text size="small" tone="quaternary">{r.owner_repo || "(no origin)"}</Text>
              </Stack>,
              <Text size="small">{r.reason}</Text>,
              <Code>{r.worktrees[0]?.branch || "—"}</Code>,
              <Text size="small" tone="secondary">{repoAction(r)}</Text>,
            ])}
          />
        </Stack>
      ) : null}
    </Stack>
  );
}
