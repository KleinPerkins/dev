"""Run named Codex roles, then hand the draft to the existing import gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

from ..canonical import atomic_write, canonical_json, contained_path, digest_ref, parse_json_object
from ..gsd_adapter import AuthoringScope, prepare_authoring_import
from ..operation_store import private_state_root, store_preview
from ..transactions import ObservedInput
from .codex_authoring_scope import MAX_INPUT_BYTES, MAX_INPUT_FILES, PROJECT_OUTPUTS, scope
from .host_assets import _tool_path, client_environment, verify_assets
from .native_authoring_import import VerifiedNativeCheck, _native_output_paths, preview_native_draft
from .native_authoring_runner import RoleRequest, run_role
from .native_runtime_stage import PACKAGE_PATH


def _owner(binding: dict):
    # Load only the exact bytes admitted by the merged owner pin. A private
    # fresh file also avoids reusing an unrelated Python bytecode cache.
    owner_path = contained_path(Path(binding["source_root"]).parent, "named_authoring.py")
    raw = owner_path.read_bytes()
    if digest_ref(raw) != binding["owner_pin"]["module_digest"]:
        raise ValueError("native_authoring_owner_module_changed")
    name = "_doc_warden_named_authoring_" + binding["owner_pin"]["revision"]
    with tempfile.TemporaryDirectory(prefix="doc-warden-named-sdk-") as staging:
        copy = Path(staging) / "named_authoring.py"
        copy.write_bytes(raw)
        copy.chmod(0o400)
        spec = importlib.util.spec_from_file_location(name, copy)
        if spec is None or spec.loader is None:
            raise ValueError("native_authoring_owner_module_unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
        if copy.read_bytes() != raw:
            raise ValueError("native_authoring_owner_module_changed")
    return module


def _inputs(project: Path, chosen) -> dict[str, bytes]:
    relatives = set(PROJECT_OUTPUTS)
    relatives.update(relative for relative, _ in chosen.input_digests)
    if chosen.phase is not None:
        directory = Path(chosen.output_paths[0]).parent
        paths = contained_path(project, (directory / ".scope").as_posix()).parent
        for path in paths.iterdir():
            if path.name.endswith(("-PLAN.md", "-CONTEXT.md", "-SUMMARY.md", "-RESEARCH.md", "-VALIDATION.md")):
                relatives.add(path.relative_to(project).as_posix())
    if len(relatives) > MAX_INPUT_FILES:
        raise ValueError("native_authoring_input_bound_exceeded")
    supplied = {}
    total = 0
    expected = dict(chosen.input_digests)
    for relative in sorted(relatives):
        path = contained_path(project, relative)
        if not path.is_file():
            if relative in expected:
                raise ValueError("native_authoring_input_changed")
            continue
        info = path.stat()
        total += info.st_size
        if info.st_nlink != 1 or total > MAX_INPUT_BYTES:
            raise ValueError("native_authoring_input_bound_exceeded")
        data = path.read_bytes()
        if len(data) != info.st_size or (relative in expected and digest_ref(data) != expected[relative]):
            raise ValueError("native_authoring_input_changed")
        supplied[relative] = data
    return supplied


def _stage(work: Path, files: dict[str, bytes]) -> None:
    for relative, raw in files.items():
        destination = contained_path(work, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)


def _task(chosen, role, brief: str, file_names: list[str], prior: str, workflow: Path) -> str:
    text = (
        f"Perform the {role} duties for {chosen.skill}, mode {chosen.mode}, phase {chosen.phase or 'new project'}.\n"
        f"Use the pinned workflow at {workflow}. This operation is authoring only. "
        "Read only the staged materials and workflow. Work alone. Never spawn or delegate to another worker, "
        "write files, run the plan, or chain a phase. "
        "Ground all claims in the operator's directions and available evidence. "
        "Mark missing implementation evidence as pending. "
        f"Staged inputs: {', '.join(file_names) or 'none'}.\n"
        f"Operator directions follow:\n{brief}\n"
    )
    if prior:
        text += f"\nPrior bounded authoring observations follow:\n{prior}\n"
    return text


def _draft_outputs(report: bytes) -> dict[str, bytes]:
    try:
        value = parse_json_object(report)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("native_authoring_draft_output_invalid") from exc
    if set(value) != {"outputs"} or type(value["outputs"]) is not dict or not value["outputs"]:
        raise ValueError("native_authoring_draft_output_invalid")
    if any(type(content) is not str for content in value["outputs"].values()):
        raise ValueError("native_authoring_draft_output_invalid")
    return {path: content.encode() for path, content in value["outputs"].items()}


def prepare_native_authoring(
    project: Path, *, binding: dict, skill: str, arguments: list[str], operator_input: bytes, active_plan: str | None,
):
    """Start one bounded operation and persist only the normal consent preview."""
    if not 0 < len(operator_input) <= 32 * 1024:
        raise ValueError("native_authoring_operator_input_required")
    try:
        brief = operator_input.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("native_authoring_operator_input_invalid") from exc
    if not brief.strip():
        raise ValueError("native_authoring_operator_input_required")
    chosen = scope(project, skill, arguments)
    files = _inputs(project, chosen)
    if skill == "gsd-validate-phase" and not any(path.endswith("-PLAN.md") for path in files):
        raise ValueError("native_authoring_phase_plan_required")
    verify_assets(binding)
    owner = _owner(binding)
    base = Path(binding["source_root"]).parent
    bundle = base / "emitted/bundle"
    runtime = bundle / "gsd-core"
    workflow_name = {
        "gsd-new-project": "new-project.md", "gsd-discuss-phase": "discuss-phase.md",
        "gsd-plan-phase": "plan-phase.md", "gsd-validate-phase": "validate-phase.md",
    }[skill]
    workflow = contained_path(runtime, f"workflows/{workflow_name}")
    if not workflow.is_file():
        raise ValueError("native_authoring_workflow_unavailable")
    prepared = prepare_authoring_import(AuthoringScope(
        repo=project, operation_id=str(uuid4()), input_paths=tuple(files),
        active_plan_id=active_plan, binding_root=Path(binding["authority_root"]),
    ))
    if any(prepared.input_digests.get(name) != digest_ref(content) for name, content in files.items()):
        raise ValueError("native_authoring_input_changed")
    client = Path(binding["client"]["binary"])
    environment = client_environment(Path(binding["home"]))
    environment["RUNTIME_DIR"] = str(runtime)
    role_evidence = []
    checker = None
    with tempfile.TemporaryDirectory(prefix="doc-warden-codex-authoring-") as disposable:
        work = Path(disposable).resolve()
        subprocess.run(["git", "init", "-q", str(work)], timeout=10, check=True)
        _stage(work, files)
        draft_roles = tuple(role for role in chosen.roles if role != "gsd-plan-checker")
        if not draft_roles and skill == "gsd-discuss-phase":
            draft_roles = ("gsd-advisor-researcher",)

        def observe(role, task):
            result = run_role(
                RoleRequest(work, bundle, client, role, task),
                owner, environment=environment,
                package_digest=binding["bundle"]["package_sha256"], timeout=240,
            )
            role_evidence.append({
                "role": role, "report_digest": digest_ref(result.report),
                "selector_digest": "sha256:" + result.evidence["selector_sha256"],
                "role_config_digest": "sha256:" + result.evidence["role_sha256"],
                "model": result.evidence["model"], "effort": result.evidence["effort"],
                "verdict": result.evidence["verdict"],
            })
            return result

        prior = ""
        outputs = None
        model_paths = tuple(path for path in chosen.output_paths if path != ".planning/config.json")
        for position, role in enumerate(draft_roles):
            task = _task(chosen, role, brief, sorted(files), prior, workflow)
            last = position == len(draft_roles) - 1
            if last:
                task += (
                    "\nReturn only one JSON object with an outputs object mapping permitted "
                    "relative paths to complete file text. No enclosing Markdown fences. "
                    f"Permitted output paths: {', '.join(model_paths)}."
                )
            settled = observe(role, task)
            if last:
                outputs = _draft_outputs(settled.report)
            else:
                text = settled.report.decode()
                if len(prior) + len(text) > 64 * 1024:
                    raise ValueError("native_authoring_intermediate_report_too_large")
                prior += f"\n{role}\n{text}\n"
        if outputs is None:
            raise ValueError("native_authoring_no_draft")
        if skill == "gsd-new-project":
            if set(outputs) != set(model_paths):
                raise ValueError("native_authoring_kickoff_incomplete")
            if ".planning/config.json" in files:
                raise ValueError("native_authoring_existing_kickoff_configuration")
            outputs[".planning/config.json"] = canonical_json({
                "mode": "interactive",
                "workflow": {"use_worktrees": False, "auto_advance": False, "cross_ai_execution": False},
                "git": {"branching_strategy": "none", "create_tag": False},
                "planning": {"commit_docs": False, "search_gitignored": False},
            })
        # Validate output names and size before any draft enters the private
        # checker project. Only normal import validation can target live files.
        _native_output_paths(chosen.output_paths, outputs)
        if "gsd-plan-checker" in chosen.roles:
            _stage(work, outputs)
            task = _task(chosen, "gsd-plan-checker", brief, sorted(set(files) | set(outputs)), "", workflow)
            task += (
                "\nRead the exact proposed files in the current staged project. Check their claims, paths, tasks and "
                "verification against the requirements. Start the report with ## VERIFICATION PASSED or ## ISSUES FOUND."
            )
            checked = observe("gsd-plan-checker", task)
            checker = VerifiedNativeCheck(
                checked.run_id, checked.evidence, checked.report,
                {name: digest_ref(content) for name, content in outputs.items()},
            )
    if scope(project, skill, arguments) != chosen or _inputs(project, chosen) != files:
        raise ValueError("native_authoring_input_changed")
    verify_assets(binding)
    observation = canonical_json({
        "schema": "doc-warden/codex-draft-observation/v1",
        "operation_id": prepared.operation_id,
        "skill": skill, "mode": chosen.mode, "phase": chosen.phase,
        "runtime_digest": binding["bundle"]["bundle_digest"],
        "client_digest": binding["client"]["binary_digest"],
        "owner_module_digest": binding["owner_pin"]["module_digest"],
        "brief_digest": digest_ref(operator_input),
        "input_digests": prepared.input_digests,
        "output_digests": {name: digest_ref(content) for name, content in outputs.items()},
        "roles": role_evidence,
    })
    state = private_state_root()
    relative = f"runtime/codex/observations/{prepared.operation_id}.json"
    observation_path = atomic_write(state, relative, observation)
    try:
        plan = preview_native_draft(
            prepared, allowed=chosen.output_paths, outputs=outputs, checker=checker,
            checker_package=contained_path(base, "locked/" + PACKAGE_PATH).parent,
            checker_node=_tool_path(binding, "node"),
            adapter_inputs=(ObservedInput(str(observation_path), digest_ref(observation)),),
        )
        expiry = store_preview(plan.transaction)
    except (OSError, ValueError):
        observation_path.unlink(missing_ok=True)
        raise
    return plan.transaction, expiry, role_evidence
