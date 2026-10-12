"""Summarize content-free browser captures without treating small samples as SLO proof."""
import argparse
import json
import statistics
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', nargs='+', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    generations, saves = {}, {}
    for path in args.captures:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        for row in data.get('generations', []):
            if row.get('traceId') and row.get('stage') in {'accepted', 'first_text_committed', 'completed'}:
                generations.setdefault(row['traceId'], {})[row['stage']] = row['durationMs']
        for row in data.get('api', []):
            if row.get('resource') == 'notes' and row.get('method') in {'POST', 'PATCH'} and row.get('traceId'):
                saves[row['traceId']] = row
    def summary(values):
        return {'count': len(values), 'medianMs': statistics.median(values) if values else None,
                'minMs': min(values) if values else None, 'maxMs': max(values) if values else None}
    complete = [row for row in generations.values() if 'completed' in row]
    report = {'scope': 'observed browser captures; mixed scenarios and conditions',
        'productionSloQualified': False, 'completedGenerations': len(complete),
        'timings': {stage: summary([row[stage] for row in complete if stage in row])
                    for stage in ('accepted', 'first_text_committed', 'completed')},
        'noteWrites': summary([row['durationMs'] for row in saves.values() if 200 <= row.get('status', 0) < 300]),
        'noteWriteFailures': sum(not 200 <= row.get('status', 0) < 300 for row in saves.values()),
        'limitations': ['Not calibrated load, regional coverage or per-scenario percentile qualification.',
                        'Deduplicates trace IDs across overlapping snapshots. Capture retention can omit older events.']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
