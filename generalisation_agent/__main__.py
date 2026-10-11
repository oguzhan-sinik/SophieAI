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
    generate.add_argument("--campaign", action="store_true", help="Explicit 30 matched customers per pack; separately budgeted")
    evaluate = commands.add_parser("evaluate", help="Exercise an existing compiled export on a saved pack; diagnostic proxy evidence")
    evaluate.add_argument("manifest", type=Path, help="The pack's manifest.json, not the two-pack run manifest")
    evaluate.add_argument("workflow", type=Path)
    evaluate.add_argument("--reps", type=int, choices=(1, 2, 3), default=3)
    evaluate.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=1,
                          help="Independent offline customer cases to run at once")
    build = commands.add_parser("build", help="Build supplied inputs with calibrated synthetic feedback; master-off delegates unchanged")
    build.add_argument("briefs", nargs="+", type=Path)
    build.add_argument("--openapi", type=Path)
    build.add_argument("--seed", type=int, default=42)
    build.add_argument("--users", type=int, default=10)
    live_build = commands.add_parser('live-build', help='One 30-minute Freya build: official ten, synthetic personas, repairs, export')
    live_build.add_argument('briefs', nargs='+', type=Path)
    live_build.add_argument('--openapi', type=Path)
    live_build.add_argument('--profile', choices=('ordinary','stress'), default='ordinary')
    live_build.add_argument('--resume-run', type=Path, help='Reuse a saved root design for the exact same brief/API')
    rehearse = commands.add_parser("rehearse", help="Build development then sealed holdout packs with frozen source")
    rehearse.add_argument("--manifest", type=Path, required=True, help="The top-level two-pack manifest")
    live = commands.add_parser('live', help='Full diagnostic calls on supported supplied practice fixtures')
    live.add_argument('workflow',type=Path)
    live.add_argument('--cases',default='PUB-01')
    live.add_argument('--briefs',type=Path,nargs='+',required=True,help='Exact supplied practice source used to build this export')
    live.add_argument('--openapi',type=Path,default=Path(__file__).resolve().parents[1]/'tools/openapi.json')
    live.add_argument('--backend',choices=('chat','persona'),default='chat')
    live.add_argument('--profile',choices=('baseline','ordinary','stress'),default='ordinary')
    live.add_argument('--reps',type=int,choices=(1,2,3),default=3)
    live.add_argument('--seconds',type=int,default=1800)
    campaign = commands.add_parser('campaign',help='Measure both frozen rehearsal exports on 30 users each, three times, outside build timing')
    campaign.add_argument('--manifest',type=Path,required=True)
    campaign.add_argument('--seconds',type=int,required=True,help='Separate test budget; conservative minimum 21600 seconds')
    campaign.add_argument('--workers',type=int,choices=(1,2,3,4),default=1)
    review = commands.add_parser('review-quality',help='Validate two independent human reviews of 30 synthetic calls; no model calls')
    review.add_argument('reviews',type=Path)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == 'review-quality':
            from .quality import review_quality
            report = review_quality(args.reviews)
            print(json.dumps(report))
            return 0 if report["accepted"] else 5
        if args.command == 'live':
            settings.require('users')
            from .live import public_customer, evaluate_chat, evaluate_personas
            from .packs import model_context
            from .evaluation import read_workflow
            from agent.builder.config import KIT
            from agent.builder.freya_adapter import FreyaAdapter
            selected = args.cases.split(',')
            available = json.loads((KIT/'public-test-set.json').read_text())
            by_id = {c['id']:c for c in available}
            if set(selected)-by_id.keys(): raise ValueError('Unknown practice case')
            cases = [by_id[key] for key in selected]
            if len(set(selected)) != len(selected): raise ValueError('Duplicate practice case')
            from agent.builder.contracts import source_documents
            from agent.builder.contracts import compile_openapi
            from agent.builder.freya_adapter import public_suite
            suite, checked_cases = public_suite(source_documents(args.briefs),compile_openapi(args.openapi)['sha256'],only=selected)
            if not suite or {c['id'] for c in checked_cases} != set(selected):
                raise ValueError('Live diagnostics require matching supplied public policy/API sources')
            customers = [public_customer(case,args.profile,index,persona_only=args.backend=='persona') for index,case in enumerate(cases)]
            workflow = read_workflow(args.workflow)
            # Public practice source/API compatibility must be checked before any mutation.
            from .live import require_practice_workflow
            require_practice_workflow(workflow,cases)
            roles, trace, deadline, root = model_context(seconds=args.seconds)
            try:
                adapter = FreyaAdapter(roles.cfg,deadline,trace)
                with adapter.workspace():
                    adapter.deploy('synthetic-'+root.name,workflow)
                    evaluator = evaluate_chat if args.backend=='chat' else evaluate_personas
                    from agent.builder.config import AGENT
                    from .progress import mirrored
                    # The supplied practice scripts are public: show this test in the dashboard as it runs.
                    with mirrored(root/'live', AGENT/'artifacts'/('synthetic_'+root.name)/'evaluations'/'live'):
                        report = evaluator(adapter,cases,customers,roles,root/'live',args.reps)
                from agent.builder.artifacts import write_json
                from .config import ROOT
                target = ROOT/'artifacts'/root.name/'report.json'
                write_json(target,report,immutable=True)
                trace.close(status='complete' if report['score']['complete'] else 'incomplete')
                print(json.dumps({'report':str(target),'evidence':report['backend'],'complete':report['score']['complete']}))
                return 0 if report['score']['complete'] else 5
            except Exception:
                trace.close(status='failed')
                raise
        if args.command == 'campaign':
            settings.require('users')
            from .campaign import run_campaign
            result = run_campaign(args.manifest,args.seconds,workers=args.workers)
            print(json.dumps(result))
            return 0 if result['complete'] else 5
        if args.command == 'live-build':
            settings.require('users')
            from agent.builder.build import Builder, inputs
            from agent.builder.config import Config, missing_credentials
            from .public_build import PublicPersonaProvider
            cfg = Config.from_env()
            missing = missing_credentials(cfg)
            if missing: raise ValueError('Missing credentials: ' + ', '.join(missing))
            briefs, api = inputs(args.briefs, args.openapi)
            provider = PublicPersonaProvider(args.profile)
            result = Builder(cfg, briefs, api, evaluation_provider=provider, resume=args.resume_run).run()
            print(json.dumps(result))
            return 0 if result.get('export_path') and (result.get('final_score') or {}).get('complete') and any(
                row.get('selection_eligible') for row in provider.results.values()) else 5
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
            from agent.builder.config import Config
            top = json.loads(confined(args.manifest).read_text())
            packs = top["packs"]
            if len(packs) != 2 or [p["split"] for p in packs] != ["development", "holdout"]:
                raise ValueError("Rehearsal needs one development and one sealed holdout pack")
            if packs[0]["policy_sha256"] == packs[1]["policy_sha256"] or packs[0]["api_sha256"] == packs[1]["api_sha256"]:
                raise ValueError("Rehearsal packs must differ in policy and schema")
            frozen = source_fingerprint()
            cfg = Config.from_env()
            results = []
            for index, item in enumerate(packs):
                if frozen != source_fingerprint(): raise ValueError("Source changed between development and holdout")
                pack = load_pack(Path(item["brief"]).parent / "manifest.json")
                if item != pack[0]: raise ValueError("Top-level and pack manifests disagree")
                if pack[0].get("campaign"):
                    pack = (*pack[:3], [c for c in pack[3] if c.plan.profile == "baseline"])
                if not pack[3]: raise ValueError("Rehearsal needs complete packs with users")
                seconds_per_case = results[0].get("synthetic_seconds_per_case", 120) if results else 120
                results.append(run_build(settings, [item["brief"]], item["openapi"], pack=pack, holdout=bool(index), cfg=cfg,
                                         seconds_per_case=seconds_per_case))
            destination = confined(args.manifest).parent / "rehearsal.json"
            complete = all(r.get("export_path") and ((r.get("diagnostic") or {}).get("score", {}).get("complete") or
                           (not r.get("holdout") and (r.get("final_score") or {}).get("complete"))) for r in results)
            write_json(destination, {"source_fingerprint": frozen, "results": results, "holdout_feedback": False,
                                     "complete": complete}, immutable=True)
            print(json.dumps({"report": str(destination), "evidence": "local_proxy", "complete": complete}))
            return 0 if complete else 5 if all(r.get("export_path") for r in results) else 4
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
                manifest = generate_packs(settings, roles, root, args.seed, args.packs, 30 if args.campaign else args.users, campaign=args.campaign)
                output = {"manifest": str(manifest), "evidence": "generated_inputs_only"}
            else:
                report, _ = evaluate_workflow(workflow, policy, mapping, users, roles, deadline, root / "evaluation", args.reps,
                                             api=json.loads(Path(manifest["openapi"]).read_text()),split=manifest["split"],workers=args.workers)
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
