"""Same-host model comparison through the public Translator; no baseline promotion.

Run one process/model at a time after downloads, conversions and scoring setup.
Config determines model-native decoding; MT batches 32, LLM uses one request slot.
"""

import argparse
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from doctranslator_cli.settings import load_settings
from doctranslator_core import LlmEngineConfig, MtEngineConfig, Translator
from doctranslator_eval.datasets import Dataset, Direction
from doctranslator_eval.runs import git_state
from doctranslator_eval.scoring import CHRF_SIGNATURE, chrf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--label', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--limit', default=100, type=int)
    parser.add_argument('--repeats', default=2, type=int)
    parser.add_argument('--directions', default='zh-en')
    parser.add_argument('--mt-batch-size', type=int, default=32)
    args = parser.parse_args()
    if args.output.exists() or min(args.limit, args.repeats, args.mt_batch_size) < 1:
        parser.error('choose a new output and positive limit/repeats')
    settings = load_settings(args.config)
    cfg = settings.engine_config(settings.mode)
    if isinstance(cfg, MtEngineConfig):
        cfg = MtEngineConfig.model_validate(cfg.model_dump() | {'max_batch_size': args.mt_batch_size})
    if isinstance(cfg, LlmEngineConfig) and cfg.max_concurrency != 1:
        parser.error('comparison requires one LLM request slot')
    if isinstance(cfg, MtEngineConfig) and (cfg.device != 'cpu' or cfg.cpu_threads != 8):
        parser.error('comparison requires CPU and eight configured MT threads')
    directions = [Direction.parse(value) for value in args.directions.split(',')]
    dataset = Dataset('flores')
    commit, dirty = git_state()
    report = {
        'label': args.label, 'created_at': datetime.now(UTC).isoformat(),
        'host': platform.platform(), 'processor': platform.processor(),
        'git_commit': commit, 'git_dirty': dirty,
        'dataset': dataset.info.model_dump(), 'limit': args.limit,
        'chrf_signature': CHRF_SIGNATURE,
        'protocol': 'Warm model; startup/scoring excluded. Operator must verify CPU/8 threads/no LLM prompt cache and one model at a time from server launch provenance.',
        'scope': f'{args.limit} rows per direction: {", ".join(map(str, directions))}; exploratory comparison, not full multilingual baseline.',
        'configuration': cfg.model_dump(mode='json', exclude={'api_key', 'base_url'}),
        'runs': [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reuse loaded model across measured passes. All input/reference order is identical.
    with Translator(cfg) as translator:
        report['identity'] = translator.identity.model_dump(mode='json')
        for direction in directions:
            all_rows = dataset.load(Path('data'), direction)
            rows = all_rows[:args.limit]
            if len(rows) != args.limit:
                parser.error('limit exceeds dataset')
            translator.translate_texts([all_rows[-1].source], source=direction.source, target=direction.target)
            for repeat in range(args.repeats):
                print(f'{args.label}: {direction}, pass {repeat + 1} started', flush=True)
                started = time.perf_counter()
                hypotheses = translator.translate_texts([r.source for r in rows], source=direction.source, target=direction.target)
                elapsed = time.perf_counter() - started
                if len(hypotheses) != len(rows) or any(not h.strip() for h in hypotheses):
                    raise ValueError('missing or blank translations')
                run = {
                    'direction': str(direction), 'repeat': repeat + 1,
                    'seconds': elapsed, 'segments_per_second': len(rows) / elapsed,
                    'chrf': chrf(hypotheses, [r.reference for r in rows]),
                    'rows': [r.model_dump() | {'hypothesis': h} for r, h in zip(rows, hypotheses, strict=True)],
                }
                report['runs'].append(run)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(f'{args.label}: {len(rows)/elapsed:.3f} segments/s, chrF {run["chrf"]:.2f}', flush=True)
    report['summary'] = [
        {'direction': value,
         'median_segments_per_second': statistics.median(r['segments_per_second'] for r in report['runs'] if r['direction'] == value),
         'median_chrf': statistics.median(r['chrf'] for r in report['runs'] if r['direction'] == value)}
        for value in map(str, directions)
    ]
    report['complete'] = True
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
