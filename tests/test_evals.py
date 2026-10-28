import pytest

from evals.run_evals import check_thresholds, judge_rows


def test_missing_required_eval_score_fails_gate():
    failed, skipped = check_thresholds(
        {"groundedness": None, "citation_accuracy": 1.0},
        {"groundedness": 3.5, "citation_accuracy": 0.6},
    )

    assert failed == ["groundedness"]
    assert skipped == []


def test_skipped_llm_scores_are_partial_not_fail_or_pass():
    failed, skipped = check_thresholds(
        {"groundedness": None, "citation_accuracy": 1.0},
        {"groundedness": 3.5, "citation_accuracy": 0.6},
        skipped_metrics={"groundedness"},
    )

    assert failed == []
    assert skipped == ["groundedness"]


def test_low_score_fails_gate():
    failed, skipped = check_thresholds(
        {"citation_accuracy": 0.5},
        {"citation_accuracy": 0.6},
    )

    assert failed == ["citation_accuracy"]
    assert skipped == []


def test_judge_errors_propagate():
    def fail(**_kwargs):
        raise RuntimeError("judge unavailable")

    rows = [
        {
            "category": "direct",
            "question": "Question?",
            "reference_answer": "Reference",
            "answer": "Answer",
        }
    ]

    with pytest.raises(RuntimeError, match="judge unavailable"):
        judge_rows(rows, {"groundedness": fail, "relevance": fail})
