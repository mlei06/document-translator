"""Local FLORES subset timing/chrF experiment; never writes accepted baselines.

Run from the repository root with uv run --no-sync and a launcher-generated config.
Uses the same public Translator as document translation. Servers must already run.
"""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from doctranslator_cli.settings import load_settings
from doctranslator_core import LlmEngineConfig, Translator
from doctranslator_core.types import TranslationMode
from doctranslator_eval.datasets import ALL_DIRECTIONS, Dataset, Direction
from doctranslator_eval.runs import git_state
from doctranslator_eval.scoring import CHRF_SIGNATURE, chrf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--concurrency', default='1,4,8')
    parser.add_argument('--directions', default='zh-en')
    args = parser.parse_args()
    levels = [int(value) for value in args.concurrency.split(',')]
    if min(args.limit, args.repeats, *levels) < 1:
        parser.error('limit, repeats and concurrency must be positive')
    if args.output.exists():
        parser.error('output exists; choose a new path to preserve prior measurements')
    base = load_settings(args.config).engine_config(TranslationMode.LLM)
    if not isinstance(base, LlmEngineConfig) or base.translation_profile == 'generic':
        parser.error('a specialized LLM configuration is required')
    directions = ALL_DIRECTIONS if args.directions == 'all' else [Direction.parse(x) for x in args.directions.split(',')]
    data = Dataset('flores')
    commit, dirty = git_state()
    report = {
        'created_at': datetime.now(UTC).isoformat(),
        'git_commit': commit, 'git_dirty': dirty,
        'dataset': data.info.model_dump(), 'limit': args.limit,
        'chrf_signature': CHRF_SIGNATURE,
        'scope': 'Exploratory subset; warm server; no COMET or baseline promotion.',
        'runs': [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for direction in directions:
        all_rows = data.load(Path('data'), direction)
        rows = all_rows[:args.limit]
        if len(rows) < args.limit:
            parser.error('limit exceeds available examples')
        for repeat in range(args.repeats):
            for concurrency in levels:
                cfg = LlmEngineConfig.model_validate(base.model_dump() | {'max_concurrency': concurrency})
                with Translator(cfg) as translator:
                    # Warm up outside the measured prefix where possible.
                    translator.translate_texts([all_rows[-1].source], source=direction.source, target=direction.target)
                    started = time.perf_counter()
                    hypotheses = translator.translate_texts([r.source for r in rows], source=direction.source, target=direction.target)
                    seconds = time.perf_counter() - started
                    identity = translator.identity.model_dump(mode='json')
                result = {
                    'direction': str(direction), 'repeat': repeat + 1,
                    'concurrency': concurrency, 'seconds': seconds,
                    'segments_per_second': len(rows) / seconds,
                    'chrf': chrf(hypotheses, [r.reference for r in rows]),
                    'identity': identity,
                    'rows': [r.model_dump() | {'hypothesis': h} for r, h in zip(rows, hypotheses, strict=True)],
                }
                report['runs'].append(result)
                args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
                print(f'{base.model} {direction} c={concurrency} repeat={repeat + 1}: {len(rows) / seconds:.2f} segments/s, chrF={result["chrf"]:.2f}', flush=True)
    report['summary'] = [
        {'direction': str(direction), 'concurrency': level,
         'median_segments_per_second': statistics.median(r['segments_per_second'] for r in report['runs'] if r['direction'] == str(direction) and r['concurrency'] == level),
         'median_chrf': statistics.median(r['chrf'] for r in report['runs'] if r['direction'] == str(direction) and r['concurrency'] == level)}
        for direction in directions for level in levels
    ]
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
