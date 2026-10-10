"""Sequential paired builds from one pinned root and frozen baseline measurement."""
import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path

from ..build import Builder
from ..config import AGENT, KIT, Config
from ..artifacts import write_json


def compare(briefs, openapi, pinned=None, only=None, style=''):
    cfg = Config.from_env()
    baseline_raw = None
    baseline_suite = None
    if pinned is None:
        baseline = Builder(replace(cfg, max_depth=0, mode='scoring_only'), briefs, openapi, only=only, style=style)
        report = baseline.run()
        if not report['export_path']:
            raise RuntimeError('Baseline build failed: ' + str(report['error']))
        pinned = baseline.root / 'pinned_root.json'
        if report['root_score']:
            paths = list((baseline.root / 'evaluations').glob('*/raw_runner.json'))
            if paths:
                baseline_raw = json.loads(paths[0].read_text())
                baseline_suite = baseline.suite.key
    arms = []
    for mode in ('scoring_only', 'scoring_with_diagnostics'):
        build = Builder(replace(cfg, mode=mode), briefs, openapi, pinned=pinned, only=only, style=style)
        build.baseline_raw = baseline_raw
        build.baseline_suite = baseline_suite
        arms.append((build, build.run()))
    folder = AGENT / 'artifacts/experiments' / (arms[0][1]['run_id'] + '_paired')
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for build, report in arms:
        initial = report['root_score']['strict_pass_rate'] if report['root_score'] else None
        final = report['strict_pass_rate']
        rows.append({'mode': report['mode'], 'run_id': report['run_id'], 'root_hash': report['root_hash'], 'champion_hash': report['champion_hash'],
                     'suite_hash': build.suite.suite_hash if build.suite else None, 'seed': cfg.seed,
                     'evidence_type': report['evaluation_type'], 'root_strict_pass_rate': initial,
                     'final_search_strict_pass_rate': final, 'held_out_strict_pass_rate': report['held_out_score']['strict_pass_rate'] if report.get('held_out_score') else None,
                     'absolute_improvement': final - initial if final is not None and initial is not None and report['root_score']['suite_key'] == report['final_score']['suite_key'] else None,
                     'valid_candidates': report['valid_candidates'], 'invalid_candidates': report['invalid_candidates'],
                     'simulations': report['simulations'], 'model_calls': report['model_calls'], 'wall_seconds': report['seconds'],
                     'estimated_cost': None, 'tokens': None, 'first_improvement_minutes': None, 'repaired_failure_classes': None,
                     'hard_fail_count': report['final_score']['hard_fail_count'] if report['final_score'] else None,
                     'unknown_count': report['final_score']['unknown'] if report['final_score'] else None,
                     'status': report['status']})
    same_root = rows[0]['root_hash'] == rows[1]['root_hash'] and rows[0]['root_hash'] is not None
    same_score = arms[0][1]['root_score'] == arms[1][1]['root_score'] and arms[0][1]['root_score'] is not None
    with (folder / 'compare_modes.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    write_json(folder / 'comparison.json', {'same_root': same_root, 'same_baseline_score': same_score, 'shared_baseline_measurement': baseline_raw is not None, 'arms': rows})
    (folder / 'compare_modes.md').write_text('# Paired feedback experiment\n\n'
        + f'Same root: {same_root}. Same baseline score: {same_score}. Shared frozen baseline: {baseline_raw is not None}.\n\n'
        + '| Mode | Root | Final search score | Seconds | Simulations |\n|---|---:|---:|---:|---:|\n'
        + ''.join(f"| {r['mode']} | {r['root_strict_pass_rate']} | {r['final_search_strict_pass_rate']} | {r['wall_seconds']} | {r['simulations']} |\n" for r in rows)
        + '\nUnknown values are blank/None, never zero. Each arm has fresh ADK sessions, archive and deployment slot. '
        + 'The baseline is frozen once when generated here. With --pinned-root, independent noisy baseline measurements may differ; such a pair is not score-matched. '
        + 'Search scores are not held-out generalization results. No superiority or statistical-significance claim follows from one pair. '
        + 'Held-out validation, token cost and sample-efficiency fields remain unknown unless measured.\n')
    return {'report': str(folder / 'compare_modes.md'), 'same_root': same_root, 'same_baseline_score': same_score}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brief', nargs='+', required=True)
    parser.add_argument('--openapi', default=str(KIT / 'tools/openapi.json'))
    parser.add_argument('--pinned-root')
    parser.add_argument('--only')
    parser.add_argument('--style', default='')
    args = parser.parse_args()
    print(json.dumps(compare(args.brief, args.openapi, args.pinned_root, args.only.split(',') if args.only else None, args.style)))


if __name__ == '__main__':
    main()
