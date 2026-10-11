"""Explicit synthetic operations; disabled flags never trigger model work."""
import argparse
import json
from pathlib import Path

from .config import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic debt-collection rehearsals (local proxy evidence)")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Render and validate two synthetic brief/API packs")
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--packs", type=int, default=2)
    generate.add_argument("--users", type=int, default=10)
    evaluate = commands.add_parser("evaluate", help="Exercise an existing compiled export on a saved pack; diagnostic proxy evidence")
    evaluate.add_argument("manifest", type=Path, help="The pack's manifest.json, not the two-pack run manifest")
    evaluate.add_argument("workflow", type=Path)
    evaluate.add_argument("--reps", type=int, choices=(1, 2, 3), default=3)
    build = commands.add_parser("build", help="Build supplied inputs with calibrated synthetic feedback; master-off delegates unchanged")
    build.add_argument("briefs", nargs="+", type=Path)
    build.add_argument("--openapi", type=Path)
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--users", type=int, default=10)
    rehearse = commands.add_parser("rehearse", help="Build development then sealed holdout packs with frozen source")
    rehearse.add_argument("--manifest", type=Path, required=True, help="The top-level two-pack manifest")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "build":
            if not settings.enabled:
                from agent.builder.build import main as original_main
                forwarded = [str(p) for p in args.briefs]
                if args.openapi: forwarded += ["--openapi", str(args.openapi)]
                return original_main(forwarded)
            from .integration import run_build
            result = run_build(settings, args.briefs, args.openapi, seed=args.seed, users=args.users)
            print(json.dumps(result))
            return 0 if result.get("export_path") else 4
        if args.command == "rehearse":
            settings.require("briefs")
            settings.require("users")
            from .config import confined, ROOT
            from .packs import load_pack
            from .integration import run_build
            from .evaluation import source_fingerprint
            from agent.builder.artifacts import write_json
            top = json.loads(confined(args.manifest).read_text())
            packs = top["packs"]
            if len(packs) != 2 or [p["split"] for p in packs] != ["development", "holdout"]:
                raise ValueError("Rehearsal needs one development and one sealed holdout pack")
            if packs[0]["policy_sha256"] == packs[1]["policy_sha256"] or packs[0]["api_sha256"] == packs[1]["api_sha256"]:
                raise ValueError("Rehearsal packs must differ in policy and schema")
            frozen = source_fingerprint()
            results = []
            for index, item in enumerate(packs):
                if frozen != source_fingerprint(): raise ValueError("Source changed between development and holdout")
                pack = load_pack(Path(item["brief"]).parent / "manifest.json")
                if item != pack[0]: raise ValueError("Top-level and pack manifests disagree")
                if not pack[3]: raise ValueError("Rehearsal needs complete packs with users")
                results.append(run_build(settings, [item["brief"]], item["openapi"], pack=pack, holdout=bool(index)))
            destination = confined(args.manifest).parent / "rehearsal.json"
            write_json(destination, {"source_fingerprint": frozen, "results": results, "holdout_feedback": False}, immutable=True)
            print(json.dumps({"report": str(destination), "evidence": "local_proxy"}))
            return 0 if all(r.get("export_path") for r in results) else 4
        settings.require("briefs" if args.command == "generate" else "users")
        if args.command == "generate" and (args.packs != 2 or not 1 <= args.users <= 10):
            raise ValueError("Initial budget: two packs, one to ten users each")
        from .packs import generate_packs, load_pack, model_context
        if args.command == "evaluate":
            manifest, policy, mapping, users = load_pack(args.manifest)
            if not users: raise ValueError("Brief-only pack has no users to evaluate")
            from .evaluation import evaluate_workflow, read_workflow
            workflow = read_workflow(args.workflow)
        roles, trace, deadline, root = model_context()
        try:
            if args.command == "generate":
                manifest = generate_packs(settings, roles, root, args.seed, args.packs, args.users)
                output = {"manifest": str(manifest), "evidence": "generated_inputs_only"}
            else:
                report, _ = evaluate_workflow(workflow, policy, mapping, users, roles, deadline, root / "evaluation", args.reps,
                                             api=json.loads(Path(manifest["openapi"]).read_text()))
                from .config import ROOT
                from agent.builder.artifacts import write_json
                write_json(ROOT / "artifacts" / root.name / "report.json", report, immutable=True)
                output = {"report": str(ROOT / "artifacts" / root.name / "report.json"), "evidence": "local_proxy"}
            trace.close(status="complete", **output)
            print(json.dumps(output))
        except Exception:
            trace.close(status="failed")
            raise
    except (ValueError, KeyError, TimeoutError, OSError, RuntimeError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
