"""Render/check packs, separating builder inputs from private customer/oracle facts."""
import hashlib
import json
from pathlib import Path
import time
import uuid

from agent.builder.adk import ADKRoles
from agent.builder.artifacts import Trace, digest, write_json
from agent.builder.config import Config, Deadline
from agent.builder.contracts import compile_openapi

from . import VERSION
from .config import ROOT, confined
from .generation import customers_for, openapi_for, sample_mapping, sample_policy
from .models import CORE_RULES, Customer, Mapping, Policy, RenderedReading, RenderedBrief, SourceReading

RULE_TEXT = """Verify the customer's presence and all security fields sequentially before any debt disclosure or account access.
For a third party disclose no debt; do not verify identity. Schedule their requested callback on a working day inside the callback window, then close not_reached/callback.
Ask for the full overdue balance first. Never ask how much the customer can pay. Offer the floor once when full is too much; amounts between floor and balance inclusive are allowed. Fraction floors round to cents, half up.
A promise must be today or later, a working day and no later than the product's deadline. For a nonworking requested day offer the next working day unless it exceeds the deadline, then offer the deadline. Clarify a vague date once, then propose the deadline.
Only flat refusals or nonanswers consume persuasion attempts, counted per product. A proposed amount or date is not a refusal. First attempt offers full (or floor if full was declined) on the last working day of this week, or next week if that day is today; any second attempt offers the floor on the deadline. Stop at the band's limit.
Read product, amount and date back, then require an explicit yes before each write (or one grouped yes when grouped_confirmation is true). Corrections require a new read-back and yes. Record one promise per product; never change/cancel it in this call.
Only say recorded after an ok=true reply; after a confirmed write say the policy's notification exactly. A certainly uncommitted failure may be retried up to retry_limit. An ambiguous write must not be retried or claimed successful; close no_promise/service_error unless a later transfer takes precedence.
Hardship stops persuasion: give one short sympathy sentence and offer support once. If declined, no_promise/hardship; spontaneous offers can be recorded only when hardship_spontaneous_promise is true.
No discounts, waivers, or plans. Already-paid means this overdue payment, not an old product closure: no promise, paid. A disputed product takes no promise. A restructuring request transfers without describing a plan. For a human request ask once whether you can help, then transfer if they insist. Be honest when asked whether you are a digital assistant; invent no bank facts.
State all overdue products before asking for payment. Handle products in account order with individual bands, deadlines and offer counts. If multi_product_notes is true and there are multiple products, note each unpromised product with its actual paid/dispute/hardship/refused/service_error reason. No notes at all on a transfer.
Closure: a transfer wins when transfer_wins is true; otherwise a recorded promise wins. With no promise, all-paid is paid; otherwise no_promise with the first unpromised non-paid product's reason in account order. Failed identity closes not_verified/failed; refusing security closes not_verified/declined.
Thank the caller and say goodbye, then exactly one close_call as the last tool action. Never call another tool after closing."""


def model_context(cfg=None, seconds=1800, root=None, *, campaign=False):
    cfg = cfg or Config.from_env()
    if seconds < 30:
        raise ValueError("Test budget must be at least thirty seconds")
    root = confined(root or ROOT / "private" / (time.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]))
    root.mkdir(parents=True, exist_ok=False)
    deadline = Deadline(seconds if campaign else min(seconds, cfg.max_wall_seconds), min(cfg.reserve, seconds - 1))
    trace = Trace(root / "build_trace.log", {"component": "generalisation", "model": cfg.builder_model}, remote=False)
    from .progress import publish_progress
    publish_progress(trace)
    return ADKRoles(cfg, deadline, trace, root), trace, deadline, root


def _differences(expected, actual, prefix=""):
    """Leaf-level field diff of two JSON-like structures, for targeted rewrite feedback."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out = []
        for key in sorted(set(expected) | set(actual)):
            out += _differences(expected.get(key), actual.get(key), f"{prefix}{key}.")
        return out
    if expected == actual:
        return []
    return [f"{prefix[:-1]}: expected {expected!r}, reconstructed {actual!r}"]


def render_checked(policy, mapping, api, form, roles, dir=None):
    review = None
    for attempt in range(3):
        rendered = roles.ask("synthetic_brief_writer", "render synthetic policy",
            "Render every supplied policy fact, operation mapping and core obligation faithfully into realistic bank Markdown. "
            "Preserve the exact spelling and casing of every enum value, band name, code and identifier; quote them verbatim. "
            "Do not include JSON, an answer key, synthetic customer cases, or generator instructions. "
            "For raw format use emails, dated memos, tables and enum lists in one Markdown file, with explicit authority and effective dates. "
            "There must be no unresolved conflict. For clean format use a concise numbered specification. "
            "Do not omit inactive/optional policy meaning: account-field floors have no fraction. Identity field order and normalisation matter. "
            "State conditional core obligations accurately even when this policy makes their conditions inactive. "
            "The call variable now anchors dates. Stable call token customer_id identifies the synthetic customer. "
            "Money rounding, retry commit semantics and ambiguous-write closure must be explicit. "
            "When previous_review is supplied, correct its findings and return the complete replacement brief, not a summary or patch.",
            {"format": form, "policy": policy.model_dump(mode="json"), "mapping": mapping.model_dump(),
             "api": api, "core_obligations": RULE_TEXT, "previous_review": review}, RenderedBrief, max_tokens=12000)
        text = RenderedBrief.model_validate(rendered).markdown
        reading = roles.ask("synthetic_brief_checker", "independent semantic check",
            "Independently reconstruct the policy and operation mappings only from this brief and API. Do not infer missing rules. "
            "List unsupported/ambiguous facts in unresolved and return policy=null if a complete supported policy cannot be reconstructed. "
            "unresolved is only for brief statements that contradict the API or each other, or whose absence makes a policy field or "
            "mapping unreconstructable. Details the policy schema never carried (effective dates, presence-confirmation phrasing, "
            "behaviour outside the declared bands/enums) are not unresolved. "
            "Report supported_core_rules using only the supplied ids for obligations actually stated. "
            "An accurately stated conditional obligation is supported even when this policy makes its condition inactive; "
            "inactivity is not an unresolved ambiguity. Never count a merely named or omitted obligation as supported. "
            "This is a check of source contents, not a request to rewrite them.",
            {"brief": text, "api": api, "core_rule_ids": CORE_RULES, "core_rule_meanings": RULE_TEXT}, RenderedReading, max_tokens=12000)
        checked = RenderedReading.model_validate(reading)
        if dir:
            write_json(dir / f"attempt-{attempt + 1}.check.json", {
                "unresolved": checked.unresolved, "supported_core_rules": sorted(checked.supported_core_rules),
                "policy_matches": checked.policy == policy, "mapping_matches": checked.mapping == mapping,
                "reconstructed_policy": checked.policy.model_dump(mode="json") if checked.policy else None}, immutable=True)
        if (not checked.unresolved and checked.policy == policy and checked.mapping == mapping and set(checked.supported_core_rules) == set(CORE_RULES)):
            if dir: (dir / "final.brief.md").write_text(text + "\n")
            roles.trace.event("synthetic_render_accepted", attempt=attempt + 1, pack=dir.parent.name if dir else None)
            return text
        review = {"previous_brief": text, "unresolved": checked.unresolved,
                  "missing_core_rules": sorted(set(CORE_RULES) - set(checked.supported_core_rules)),
                  "policy_matches": checked.policy == policy, "mapping_matches": checked.mapping == mapping,
                  "policy_differences": _differences(policy.model_dump(mode="json"), checked.policy.model_dump(mode="json")) if checked.policy else ["policy was not reconstructed"],
                  "mapping_differences": _differences(mapping.model_dump(mode="json"), checked.mapping.model_dump(mode="json")) if checked.mapping else ["mapping was not reconstructed"]}
        if dir: (dir / f"attempt-{attempt + 1}.brief.md").write_text(text + "\n")
        roles.trace.event("synthetic_render_rejected", attempt=attempt + 1, pack=dir.parent.name if dir else None,
                          unresolved=checked.unresolved,
                          policy_matches=checked.policy == policy, mapping_matches=checked.mapping == mapping)
    raise ValueError("Rendered brief did not preserve all policy semantics after three attempts")


def generate_packs(settings, roles, root, seed=42, packs=2, users=10, *, campaign=False):
    settings.require("briefs")
    if packs != 2:
        raise ValueError("The approved initial rehearsal has exactly two packs")
    if not (users == 30 if campaign else 1 <= users <= 10):
        raise ValueError("User count must be between one and ten")
    root = confined(root)
    run_id = root.name
    public = confined(ROOT / "artifacts" / run_id)
    output = []
    for index in range(packs):
        pack_id = f"pack-{seed}-{index+1}"
        policy, mapping = sample_policy(seed, index), sample_mapping(index)
        api = openapi_for(policy, mapping, pack_id)
        form, split = ("clean", "development") if index == 0 else ("raw", "holdout")
        inputs = public / "packs" / pack_id
        private = root / "packs" / pack_id
        renders = private / "renders"
        renders.mkdir(parents=True, exist_ok=True)
        text = render_checked(policy, mapping, api, form, roles, renders)
        inputs.mkdir(parents=True, exist_ok=False)
        (inputs / "brief.md").write_text(text + "\n")
        write_json(inputs / "openapi.json", api, immutable=True)
        compile_openapi(inputs / "openapi.json")
        write_json(private / "policy.json", policy.model_dump(mode="json"), immutable=True)
        write_json(private / "mapping.json", mapping.model_dump(), immutable=True)
        cases = customers_for(policy, seed * 100 + index, users, campaign=campaign) if settings.users else []
        write_json(private / "users.json", [c.model_dump(mode="json") for c in cases], immutable=True)
        roles.trace.event("synthetic_users_generated", pack=pack_id, case_count=len(cases),
                          coverage=sorted({c.family for c in cases}),
                          cases=[{"id": c.id, "family": c.family, "style": c.style, "third_party": c.third_party,
                                  "actions": [g.action for g in c.goals], "faults": [f.mode for f in c.faults],
                                  "wrong_answers": sorted(c.wrong_answers)} for c in cases])
        manifest = {"version": VERSION, "id": pack_id, "split": split, "format": form, "seed": seed,
                    "settings": settings.manifest(), "builder_model": roles.cfg.builder_model,
                    "brief": str(inputs / "brief.md"), "openapi": str(inputs / "openapi.json"),
                    "brief_sha256": hashlib.sha256((inputs / "brief.md").read_bytes()).hexdigest(),
                    "api_sha256": digest(api), "policy_sha256": digest(policy.model_dump(mode="json")),
                    "mapping_sha256": digest(mapping.model_dump()), "users_sha256": digest([c.model_dump(mode="json") for c in cases]),
                    "case_count": len(cases), "complete_pack": bool(cases), "campaign": campaign,
                    "behaviour_plan_sha256": digest([c.plan.model_dump(mode='json') for c in cases]),
                    "profiles": sorted({c.plan.profile for c in cases}),
                    "planned_behaviours": sorted({e.id for c in cases for e in c.plan.events}),
                    "coverage": sorted({c.family for c in cases})}
        write_json(inputs / "manifest.json", manifest, immutable=True)
        write_json(private / "manifest.json", manifest, immutable=True)
        output.append(manifest)
    if output[0]["policy_sha256"] == output[1]["policy_sha256"] or output[0]["api_sha256"] == output[1]["api_sha256"]:
        raise ValueError("Development and holdout must differ in policy and schema")
    write_json(public / "manifest.json", {"run_id": run_id, "settings": settings.manifest(), "packs": output}, immutable=True)
    roles.trace.event("synthetic_packs_generated", pack_count=len(output), case_count=sum(p["case_count"] for p in output))
    return public / "manifest.json"


def load_pack(manifest_path):
    path = confined(manifest_path)
    manifest = json.loads(path.read_text())
    if manifest.get("version") != VERSION:
        raise ValueError("Pack version changed; regenerate packs before evaluating the revised harness")
    if not path.is_relative_to(ROOT / "artifacts") or path.name != "manifest.json" or path.parent.parent.name != "packs":
        raise ValueError("Expected an artifact pack manifest")
    if manifest["id"] != path.parent.name:
        raise ValueError("Pack identity/path mismatch")
    private = confined(ROOT / "private" / path.parents[2].name / "packs" / path.parent.name)
    policy = Policy.model_validate_json((private / "policy.json").read_text())
    mapping = Mapping.model_validate_json((private / "mapping.json").read_text())
    users = [Customer.model_validate(c) for c in json.loads((private / "users.json").read_text())]
    api_path, brief_path = confined(manifest["openapi"]), confined(manifest["brief"])
    if api_path != path.parent / "openapi.json" or brief_path != path.parent / "brief.md":
        raise ValueError("Pack inputs must belong to their own manifest directory")
    values = {"policy_sha256": digest(policy.model_dump(mode="json")), "mapping_sha256": digest(mapping.model_dump()),
              "users_sha256": digest([c.model_dump(mode="json") for c in users]),
              "behaviour_plan_sha256": digest([c.plan.model_dump(mode="json") for c in users]),
              "api_sha256": digest(json.loads(api_path.read_text())), "brief_sha256": hashlib.sha256(brief_path.read_bytes()).hexdigest()}
    if any(manifest.get(key) != value for key, value in values.items()):
        raise ValueError("Pack inputs or sealed expectations changed after generation")
    return manifest, policy, mapping, users


def interpret_source(brief, api, roles):
    lines = brief.splitlines()
    reading = SourceReading.model_validate(roles.ask("synthetic_source_analyst", "independent live policy interpretation",
        "Extract policy and mappings independently from the real brief/API. Never use a builder workflow or builder requirements. "
        "Report unsupported rules, source conflicts and missing fields in unresolved; return null policy/mapping when not fully supported. "
        "No invented defaults. Cite every top-level Policy field and every supported core rule with exact numbered source lines. "
        "Accurately documented conditional obligations count as supported even when inactive in this policy; "
        "a merely named or omitted obligation does not. Inactivity alone is not unresolved ambiguity. "
        "Use semantic request mappings and response/product names actually declared by the API.",
        {"numbered_brief": "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1)), "api": api,
         "core_rule_ids": CORE_RULES, "core_rule_meanings": RULE_TEXT}, SourceReading, max_tokens=14000))
    if not reading.policy or not reading.mapping or reading.unresolved:
        return reading
    fields = set(Policy.model_fields) | set(CORE_RULES)
    for citation in reading.citations:
        if not 1 <= citation.start_line <= citation.end_line <= len(lines) or not citation.quote.strip() or citation.quote not in "\n".join(lines[citation.start_line-1:citation.end_line]):
            raise ValueError("Live interpretation has an invalid source citation")
    if fields - {c.field for c in reading.citations} or set(reading.supported_core_rules) != set(CORE_RULES):
        return reading.model_copy(update={"unresolved": ["Incomplete source coverage for supported policy semantics"]})
    return reading
