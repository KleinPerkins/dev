import {
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Code,
  Divider,
  H1,
  H2,
  Row,
  Stack,
  Table,
  Text,
  useCanvasAction,
  useHostTheme,
} from "cursor/canvas";

type RoadmapItem = {
  schema?: string;
  id?: string;
  kind?: string;
  outcome?: string;
  priority?: string;
  sequence?: number;
  wave?: number | null;
  status?: string;
  dependencies?: {
    planned?: string[];
    observed?: string[];
  };
  required_artifacts?: string[];
  active_versions?: Record<string, number>;
  active_plan?: string | null;
  blockers?: string[];
  next_action?: string;
  completion_evidence?: string[];
  freshness?: {
    source_revision?: string;
    observed_at?: string;
  };
};

type FleetRepository = {
  repository?: string;
  repository_key?: string | null;
  repository_id?: number | null;
  designated_path?: string | null;
  available?: boolean;
  reason?: string | null;
  owner?: string;
  next_action?: string;
  mutation_eligible?: boolean;
  docs_only?: boolean;
  checkout_count?: number;
  source_revision?: string | null;
  observed_at?: string | null;
};

type Snapshot = {
  schema: string;
  mode: "repo" | "fleet";
  source_revision: string;
  source_observed_at: string;
  generated_at: string;
  read_only: true;
  repository_writes: [];
  repository_key?: string | null;
  migration_status?: string;
  reason?: string;
  items?: RoadmapItem[];
  dependencies?: string[][];
  cycles?: string[][];
  repositories?: FleetRepository[];
  refresh_action: string;
  manage_action: string;
};

// DOC_WARDEN_DATA_BEGIN
const SNAPSHOT: Snapshot | null = null;
// DOC_WARDEN_DATA_END

// M3-T02: Plain-language translation helpers for fleet presentation.
// Maps internal reason/action codes to operator prose at the presentation boundary.
// Machine-readable field values in the JSON snapshot are left unchanged.
const REASON_LABELS: Record<string, string> = {
  checkout_unavailable_from_selected_worktree: "Not checked out in current session",
  identity_conflict: "Conflicting checkouts detected",
};
const NEXT_ACTION_LABELS: Record<string, string> = {
  inspect_current_checkout: "Inspect current checkout",
  open_or_locate_checkout: "Open or locate checkout",
  observe_only: "Observe only — not a governance target",
};
function labelReason(code: string | null | undefined): string {
  if (!code) return "—";
  return REASON_LABELS[code] ?? code.replace(/_/g, " ");
}
function labelNextAction(code: string | null | undefined): string {
  if (!code) return "Review";
  return NEXT_ACTION_LABELS[code] ?? code.replace(/_/g, " ");
}
// Catalog scope: distinguishes active registry targets from explicit exclusions,
// and labels target availability as session-observed rather than existential.
function catalogScope(repository: FleetRepository): string {
  if (repository.repository_id == null) {
    return repository.docs_only ? "Docs-only exclusion" : "Explicit exclusion";
  }
  return repository.available
    ? "Observed in this session"
    : "Not observed in this session";
}

export default function DocWardenRoadmap() {
  const dispatch = useCanvasAction();
  const theme = useHostTheme();

  const refreshPrompt = (scope: "repo" | "fleet") =>
    scope === "repo"
      ? "Refresh this @mentioned read-only doc-warden repository roadmap by running `bash _ops/bin/doc-warden.sh view repo --canvas <this-canvas-path>`. If the command or Canvas path is unavailable, report that refresh is unavailable and do not claim success. Do not apply or author anything."
      : "Refresh this @mentioned read-only doc-warden fleet roadmap by running `bash _ops/bin/doc-warden.sh view fleet --canvas <this-canvas-path>`. If the command or Canvas path is unavailable, report that refresh is unavailable and do not claim success. Do not apply or author anything.";

  const requestRefresh = (scope: "repo" | "fleet") =>
    dispatch({
      type: "newComposerChat",
      userPrompt: refreshPrompt(scope),
    });

  const managePrompt =
    "Manage doc-warden governance in chat. Start with the read-only `bash _ops/bin/doc-warden.sh view repo` and `doctor repo` commands. For any change, use the validated CLI preview and operation-bound confirmation flow; never mutate from the Canvas.";

  const roadmapRows = (SNAPSHOT?.items ?? []).map((item) => [
    item.outcome ?? item.id ?? "Governed item",
    item.kind ?? "product",
    item.priority ?? "unassigned",
    item.sequence == null
      ? "unsequenced"
      : `${item.sequence}${item.wave == null ? "" : ` / wave ${item.wave}`}`,
    item.status ?? "unknown",
    item.blockers?.length ? item.blockers.join(", ") : item.next_action ?? "Review",
  ]);

  const fleetRows = (SNAPSHOT?.repositories ?? []).map((repository) => [
    repository.repository ?? "Governed repository",
    catalogScope(repository),
    repository.docs_only
      ? "Documentation only"
      : repository.repository_id == null
        ? "Explicit exclusion"
        : "Governance target",
    labelReason(repository.reason),
    repository.source_revision?.slice(0, 12) ?? "—",
    repository.observed_at ?? "—",
    labelNextAction(repository.next_action),
  ]);

  return (
    <Stack gap={22} style={{ color: theme.text.primary, maxWidth: 1180 }}>
      <Row gap={16} align="start" justify="space-between" wrap>
        <Stack gap={6} style={{ minWidth: 320 }}>
          <Text size="small" tone="tertiary" weight="semibold">
            DOCUMENTATION GOVERNANCE
          </Text>
          <H1>{SNAPSHOT?.mode === "fleet" ? "Fleet roadmap" : "Repository roadmap"}</H1>
          <Text tone="secondary">
            {SNAPSHOT
              ? "A generated, read-only view bound to one source revision."
              : "This tracked seed contains no repository data. Refresh in chat to generate a source-revision-bound repo or fleet snapshot."}
          </Text>
        </Stack>
        <Row gap={8} wrap>
          <Button variant="primary" onClick={() => requestRefresh(SNAPSHOT?.mode ?? "repo")}>
            Refresh via agent
          </Button>
          <Button
            variant="secondary"
            onClick={() => requestRefresh(SNAPSHOT?.mode === "fleet" ? "repo" : "fleet")}
          >
            {SNAPSHOT?.mode === "fleet"
              ? "Repository view via agent"
              : "Fleet view via agent"}
          </Button>
          <Button
            variant="ghost"
            onClick={() =>
              dispatch({
                type: "newComposerChat",
                userPrompt: managePrompt,
              })
            }
          >
            Manage in chat
          </Button>
        </Row>
      </Row>

      {SNAPSHOT ? (
        <Stack gap={10}>
          <Divider />
          <Row gap={18} wrap>
            <Text size="small" tone="secondary">
              {SNAPSHOT.mode === "fleet" ? "Catalog at" : "Source"}{" "}
              <Code>{SNAPSHOT.source_revision.slice(0, 12)}</Code>
            </Text>
            <Text size="small" tone="secondary">
              {SNAPSHOT.mode === "fleet" ? "Catalog observed" : "Source observed"}{" "}
              {SNAPSHOT.source_observed_at}
            </Text>
            <Text size="small" tone="secondary">
              Snapshot generated {SNAPSHOT.generated_at}
            </Text>
            <Text size="small" tone="secondary">
              {SNAPSHOT.items?.length ?? SNAPSHOT.repositories?.length ?? 0} visible rows
            </Text>
          </Row>
        </Stack>
      ) : null}

      <Callout tone="info">
        Generated snapshots are read-only. Priority, sequencing, migration, repair, and
        semantic changes always return to chat and the validated doc-warden CLI.
      </Callout>

      {SNAPSHOT?.reason ? (
        <Callout tone="warning">
          Governance view is blocked: {SNAPSHOT.reason}. Manage the recovery in chat.
        </Callout>
      ) : null}

      {roadmapRows.length ? (
        <Stack gap={10}>
          <H2>Roadmap outcomes</H2>
          <Table
            headers={["Outcome", "Kind", "Priority", "Sequence", "Status", "Next action"]}
            rows={roadmapRows}
            striped
          />
        </Stack>
      ) : null}

      {fleetRows.length ? (
        <Stack gap={10}>
          <H2>Governed repositories</H2>
          <Callout tone="info">
            Registry-scoped catalog projection — shows the committed runnerless registry (active
            targets and explicit exclusions), not live checkout discovery. Availability reflects
            whether a checkout was observed in the current agent session.
          </Callout>
          <Card>
            <CardHeader>How to read this view</CardHeader>
            <CardBody>
              <Stack gap={10}>
                {(
                  [
                    {
                      term: "Registry-scoped catalog projection",
                      def: "This view shows the committed doc-warden fleet registry — which repositories are actively governed and which are intentional exclusions. It is not live checkout discovery and does not reflect what is installed on any machine right now.",
                    },
                    {
                      term: "Governance target",
                      def: "The repository is identified in the doc-warden registry as an actively governed fleet member. This is not proof of a local checkout and is not permission or authorization to write to it.",
                    },
                    {
                      term: "Documentation only",
                      def: "Shown here for awareness and reference. Excluded from automated repository mutation.",
                    },
                    {
                      term: "Explicit exclusion",
                      def: "Intentionally outside active governance scope. See the Reason column for why.",
                    },
                    {
                      term: "Observed in this session",
                      def: "A checkout of this repository was located during the current agent session.",
                    },
                    {
                      term: "Not observed in this session",
                      def: "No checkout was found during the current agent session. The repository may still be a governance target. Session observation is a session-level snapshot, not a fleet-wide live inventory.",
                    },
                    {
                      term: "Reason",
                      def: "Why this row has its current catalog or session-observation state.",
                    },
                    {
                      term: "Next action",
                      def: "A recommendation routed through chat and the validated doc-warden CLI. It is a proposal, not an action already taken and not automatic authorization to execute.",
                    },
                  ] as { term: string; def: string }[]
                ).map(({ term, def }) => (
                  <Row key={term} gap={14} align="start">
                    <Text
                      weight="semibold"
                      size="small"
                      style={{ minWidth: 220, flexShrink: 0 }}
                    >
                      {term}
                    </Text>
                    <Text size="small" tone="secondary">
                      {def}
                    </Text>
                  </Row>
                ))}
              </Stack>
            </CardBody>
          </Card>
          <Table
            headers={["Repository", "Catalog status", "Governance", "Reason", "Revision", "Observed at", "Next action"]}
            rows={fleetRows}
            striped
          />
        </Stack>
      ) : null}
    </Stack>
  );
}
