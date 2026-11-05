"""Rebuild a finished run's .partial.jsonl from its results file, so that
`run_eval.py --resume ... --rejudge ID` can judge a stored answer again after the run finalized
(EVAL_RESULTS.md, Phase 5 gate run, q055/q056).

    uv run python eval/reopen_result.py eval/results/<run_id>.json

Lossless: the results file holds the original meta, every record and every session. The keys that finalizing
adds to meta are removed so the resumed run recomputes them. Refuses to overwrite an existing partial.
"""

import json
import sys
from pathlib import Path

FINALIZE_KEYS = ("sessions", "finished_utc", "elapsed_min", "git_commits", "generator_model")


def reopen(result_path: Path) -> Path:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    meta = {k: v for k, v in result["meta"].items() if k not in FINALIZE_KEYS}
    partial = result_path.with_name(f"{meta['run_id']}.partial.jsonl")
    if partial.exists():
        raise SystemExit(f"{partial} already exists")
    lines = [{"meta": meta}, *result["records"], *({"session": s} for s in result["meta"]["sessions"])]
    partial.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), encoding="utf-8")
    return partial


if __name__ == "__main__":
    print(reopen(Path(sys.argv[1])))
