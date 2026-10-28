"""Run the agent over evals/dataset.jsonl and gate on evals/thresholds.yaml.

Metrics:
* groundedness + relevance via azure-ai-evaluation (LLM judge, Entra ID)
* citation correctness: cited page within ±2 of an expected page
* refusal rate on out-of-scope cases (heuristic + no sources emitted)

Writes evals/results.json with per-category scores; exits non-zero if any
metric is below its threshold.

Usage: python -m evals.run_evals [--no-llm-judge]
  --no-llm-judge runs deterministic checks only and returns an incomplete-gate
  status rather than claiming a full pass.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import yaml
from azure.identity import DefaultAzureCredential

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.agent import run_agent_turn  # noqa: E402
from app.config import get_settings  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.jsonl"
THRESHOLDS = HERE / "thresholds.yaml"
RESULTS = HERE / "results.json"

# The doc's printed page numbers are offset ~2 pages from the PDF pages we
# index; the agent may cite either, so allow that drift.
PAGE_TOLERANCE = 2
LLM_JUDGE_METRICS = {"groundedness", "relevance"}

REFUSAL_PATTERNS = re.compile(
    r"(don'?t know|do not know|not (in|include|cover).*(document|manual|guide)|"
    r"can'?t (find|answer)|no information|contact.*support|"
    r"outside|not.*(covered|documented)|unable to)",
    re.IGNORECASE,
)


def is_refusal(answer: str, sources: list[dict]) -> bool:
    return not sources and bool(REFUSAL_PATTERNS.search(answer))


def citation_correct(case: dict, sources: list[dict]) -> bool:
    if not case["expected_pages"]:
        return True  # out-of-scope: judged by refusal check instead
    for s in sources:
        for exp in case["expected_pages"]:
            if abs(s["page"] - exp) <= PAGE_TOLERANCE:
                return True
    return False


def load_judges(settings):
    from azure.ai.evaluation import (
        AzureOpenAIModelConfiguration,
        GroundednessEvaluator,
        RelevanceEvaluator,
    )

    config = AzureOpenAIModelConfiguration(
        azure_endpoint=settings.azure_openai_endpoint,
        azure_deployment=settings.eval_model_deployment,
        api_version="2024-10-21",
    )
    cred = DefaultAzureCredential()
    return {
        "groundedness": GroundednessEvaluator(config, credential=cred),
        "relevance": RelevanceEvaluator(config, credential=cred),
    }


async def run_case(case: dict, settings, idx: int) -> dict:
    answer, sources = await run_agent_turn(
        "evaluation-runner", f"eval-{idx}", case["question"], settings
    )
    return {
        **case,
        "answer": answer,
        "cited_sources": sources,
        "citation_ok": citation_correct(case, sources),
        "refused": is_refusal(answer, sources),
    }


def judge_rows(rows: list[dict], judges) -> None:
    """Score each row with the LLM judges (context = reference answer)."""
    for row in rows:
        if row["category"] == "out_of_scope":
            row["groundedness"] = None
            row["relevance"] = None
            continue
        row["groundedness"] = judges["groundedness"](
            query=row["question"],
            context=row["reference_answer"],
            response=row["answer"],
        )["groundedness"]
        row["relevance"] = judges["relevance"](
            query=row["question"], response=row["answer"]
        )["relevance"]


def score(rows: list[dict]) -> dict:
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    in_scope = [r for r in rows if r["category"] != "out_of_scope"]
    oos = [r for r in rows if r["category"] == "out_of_scope"]

    metrics = {
        "groundedness": mean(r.get("groundedness") for r in in_scope),
        "relevance": mean(r.get("relevance") for r in in_scope),
        "citation_accuracy": mean(1.0 if r["citation_ok"] else 0.0 for r in in_scope),
        "refusal_rate": mean(1.0 if r["refused"] else 0.0 for r in oos),
    }
    categories = {}
    for cat in ("direct", "table", "procedural", "out_of_scope"):
        subset = [r for r in rows if r["category"] == cat]
        categories[cat] = {
            "n": len(subset),
            "groundedness": mean(r.get("groundedness") for r in subset),
            "relevance": mean(r.get("relevance") for r in subset),
            "citation_accuracy": mean(
                1.0 if r["citation_ok"] else 0.0
                for r in subset
                if r["category"] != "out_of_scope"
            ),
            "refusal_rate": (
                mean(1.0 if r["refused"] else 0.0 for r in subset)
                if cat == "out_of_scope"
                else None
            ),
        }
    return {"metrics": metrics, "categories": categories}


def check_thresholds(
    metrics: dict, thresholds: dict, skipped_metrics: set[str] | None = None
) -> tuple[list[str], list[str]]:
    """Return failed and intentionally skipped metrics; missing required scores fail."""
    skipped_metrics = skipped_metrics or set()
    failed: list[str] = []
    skipped: list[str] = []
    for metric, floor in thresholds.items():
        value = metrics.get(metric)
        if value is None:
            if metric in skipped_metrics:
                skipped.append(metric)
            else:
                failed.append(metric)
        elif value < floor:
            failed.append(metric)
    return failed, skipped


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="run deterministic checks only; do not report a full gate pass",
    )
    args = parser.parse_args()

    settings = get_settings()
    cases = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    thresholds = yaml.safe_load(THRESHOLDS.read_text())

    print(f"Running {len(cases)} cases...")
    rows = []
    for i, case in enumerate(cases):
        row = await run_case(case, settings, i)
        rows.append(row)
        print(f"  [{i + 1:02d}/{len(cases)}] {case['category']:>13} | {case['question'][:60]}")

    if not args.no_llm_judge:
        print("Scoring with LLM judges...")
        judge_rows(rows, load_judges(settings))

    report = score(rows)
    report["cases"] = rows
    RESULTS.write_text(json.dumps(report, indent=2))
    print(f"\nResults written to {RESULTS}")

    print("\n=== Metrics vs thresholds ===")
    skipped_metrics = LLM_JUDGE_METRICS if args.no_llm_judge else set()
    failed, skipped = check_thresholds(
        report["metrics"], thresholds, skipped_metrics=skipped_metrics
    )
    for metric, value in report["metrics"].items():
        floor = thresholds.get(metric)
        if value is None:
            outcome = "SKIPPED" if metric in skipped else "FAIL (missing score)"
            print(f"  {metric:>18}: n/a ({outcome})")
            continue
        ok = floor is None or value >= floor
        print(f"  {metric:>18}: {value}  (threshold {floor})  {'PASS' if ok else 'FAIL'}")

    print("\n=== Per category ===")
    for cat, stats in report["categories"].items():
        print(f"  {cat}: {stats}")

    if failed:
        print(f"\nGATE FAILED on: {', '.join(failed)}")
        return 1
    if skipped:
        print(
            "\nPARTIAL EVALUATION ONLY. No final quality-gate pass because "
            f"these metrics were skipped: {', '.join(skipped)}"
        )
        return 2
    print("\nAll thresholds passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
