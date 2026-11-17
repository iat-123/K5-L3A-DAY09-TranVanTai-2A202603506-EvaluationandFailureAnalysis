"""Regression test from docs/trace_case.md: seeded_regression C-002@11.

First wrong step = event 3 `model_override {"delay_days": 5}` (ticket's 5 days replaces the DB's
delay). Graders that must catch it: DbFactKept (step) and RefundAmountCorrect (ledger).
Run: python -m pytest -q -m student -o addopts= -k trace_case
"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape: str):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, "C-002", 11)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {n: g().evaluate(ctx).value for n, g in graders.GRADERS.items()}


def test_lab9_trace_case_seeded_regression_c002_fails_at_override():
    trial, v = _grade("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    # the first step that differs from `fixed` is the override, right after the investigator
    assert kinds.index("model_override") == kinds.index("investigator") + 1
    assert v["db_fact_kept"] is False
    assert v["refund_amount_correct"] is False
    assert v["pass_rate"] is False


def test_lab9_trace_case_fixed_c002_passes():
    trial, v = _grade("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert v["db_fact_kept"] and v["refund_amount_correct"] and v["pass_rate"]
    assert v["approval_bypass"] is False and v["secret_leak"] is False
