"""Fictional owner-path staging plans only; no clients or sends."""

import copy

import pytest
from test_canvas_primary_review import binding as binding
from test_canvas_primary_review import case as case
from test_canvas_primary_review import snapshot as snapshot
from test_gradebook_native import initial_raw

from canvas_mcp.gradebook.canvas_primary_current_attempt import make_binding
from canvas_mcp.gradebook.canvas_primary_review import (
    prepare_primary_review_transfer,
    revalidate_primary_review_transfer,
)
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest


@pytest.fixture(params=["blank", "zero"])
def stale(case, request):
    b = case["baseline"]["cells"]["101:21"]
    b.update(
        attempt=None,
        submitted_at=None,
        workflow_state="unsubmitted",
        value=None,
        grade=None,
        graded_at=None,
        posted_at=None,
        grade_matches_current_submission=True,
        points_deducted=None,
        late=False,
        late_policy_status=None,
        missing=False,
    )
    if request.param == "zero":
        b.update(
            workflow_state="graded",
            value=0.0,
            grade="0",
            graded_at="2026-11-01T12:00:00Z",
            posted_at="2026-11-01T12:00:00Z",
        )
    c = copy.deepcopy(b)
    c.update(
        attempt=2,
        submitted_at="2026-11-12T12:00:00Z",
        workflow_state="submitted",
        value=0.0,
        grade="0",
        graded_at="2026-11-01T12:00:00Z",
        posted_at="2026-11-01T12:00:00Z",
        grade_matches_current_submission=False,
    )
    case["current"]["cells"]["101:21"] = c
    case["record"].update(canvas_attempt=2, raw_score=8, raw_maximum=9)
    case["evidence"]["canvas_attempt"] = 2
    meta = case["assignment_binding"]["assignment_metadata"]
    meta.update(published=True, grading_type="points", points_possible=20)
    case["assignment_binding"]["assignment_metadata_sha256"] = digest(meta)
    case["evidence"]["assignment_sha256"] = digest(meta)
    for snap in (case["baseline"], case["current"]):
        a = next(a for a in snap["assignments"] if a["id"] == "21")
        a.update(
            assignment_metadata=copy.deepcopy(meta),
            assignment_metadata_sha256=digest(meta),
        )
    case["raw"] = initial_raw(case["baseline"], case["binding"])
    rebind(case)
    return case


def rebind(c):
    e = c["evidence"]
    e.update(
        record_sha256=digest(c["record"]),
        proposal_sha256=digest(c["proposal"]),
        current_cell_sha256=digest(c["current"]["cells"]["101:21"]),
    )
    e["current_attempt_review"] = make_binding(
        **{
            k: c[k]
            for k in (
                "evidence",
                "record",
                "proposal",
                "assignment_binding",
                "binding",
                "raw",
                "baseline",
                "current",
                "pin_binding",
                "protection_registry",
            )
        }
    )
    expected = copy.deepcopy(e)

    def authority(actual):
        if actual != expected:
            raise ValueError("review changed")

    c["authority"] = authority


def test_exact_unapproved_plan(stale):
    before = copy.deepcopy(stale)
    p = prepare_primary_review_transfer(**stale)
    assert stale == before
    t = p["transfer"]
    assert t["baseline"] == stale["baseline"]
    assert t["current_basis"]["cell"]["grade_matches_current_submission"] is False
    assert t["requests"][0]["updateCells"]["fields"] == "userEnteredValue"
    assert "current_attempt_comparison_sha256" in t
    assert p["publication_allowed"] is False
    revalidate_primary_review_transfer(
        p,
        expected_plan_sha256=digest(p),
        authority=stale["authority"],
        protection_registry=stale["protection_registry"],
        protection_authority=stale["protection_authority"],
        raw=stale["raw"],
        current=stale["current"],
        pin_binding=stale["pin_binding"],
    )


@pytest.mark.parametrize(
    "mutation", ["both", "receipt", "grade", "source", "protection"]
)
def test_integration_holds(stale, mutation):
    if mutation == "both":
        stale["evidence"]["first_submission_review"] = {}
    elif mutation == "receipt":
        stale["evidence"]["current_attempt_review"]["scope"] = "APPROVED"
    elif mutation == "grade":
        stale["current"]["cells"]["101:21"]["value"] = 20
    elif mutation == "source":
        stale["authority"] = lambda e: (_ for _ in ()).throw(ValueError("stale"))
    else:
        stale["protection_authority"] = lambda *a: (_ for _ in ()).throw(
            ValueError("protected")
        )
    with pytest.raises(GradebookError):
        prepare_primary_review_transfer(**stale)


@pytest.mark.parametrize(
    "mutation", ["note", "formula", "attempt", "receipt", "registry"]
)
def test_retained_revalidation_holds(stale, mutation):
    from test_gradebook_native import raw_from_state

    from canvas_mcp.gradebook import native

    p = prepare_primary_review_transfer(**stale)
    if mutation in ("note", "formula"):
        state = native._state(stale["raw"])
        cell = state["sheets"][stale["binding"]["sheets"]["Working"]][
            "cells"
        ].setdefault("5:2", {})
        if mutation == "note":
            cell["note"] = "new teacher comment"
        else:
            cell["userEnteredValue"] = {"formulaValue": "=0"}
        stale["raw"] = raw_from_state(state)
    elif mutation == "attempt":
        stale["current"]["cells"]["101:21"]["attempt"] = 3
    elif mutation == "receipt":
        p["evidence"]["current_attempt_review"]["scope"] = "APPROVED"
    else:
        stale["protection_registry"]["population_evidence_sha256"] = "0" * 64
    with pytest.raises(GradebookError):
        revalidate_primary_review_transfer(
            p,
            expected_plan_sha256=digest(p),
            authority=stale["authority"],
            protection_registry=stale["protection_registry"],
            protection_authority=stale["protection_authority"],
            raw=stale["raw"],
            current=stale["current"],
            pin_binding=stale["pin_binding"],
        )


def test_exact_observed_format_current_attempt(stale):
    from test_canvas_primary_review import observed_first_submission_case

    c = observed_first_submission_case.__wrapped__(stale)
    c["evidence"].pop("first_submission_review")
    rebind(c)
    expected_raw = copy.deepcopy(c["raw"])

    def observed(raw, binding, baseline, receipt):
        if raw != expected_raw or receipt != c["evidence"]["observed_format_sha256"]:
            raise ValueError("changed raw format")

    c["observed_format_authority"] = observed
    p = prepare_primary_review_transfer(**c)
    assert c["raw"] == expected_raw
    assert p["transfer"]["requests"][0]["updateCells"]["fields"] == "userEnteredValue"
    revalidate_primary_review_transfer(
        p,
        expected_plan_sha256=digest(p),
        authority=c["authority"],
        protection_registry=c["protection_registry"],
        protection_authority=c["protection_authority"],
        observed_format_authority=observed,
        raw=c["raw"],
        current=c["current"],
        pin_binding=c["pin_binding"],
    )
    c["observed_format_authority"] = None
    with pytest.raises(GradebookError):
        prepare_primary_review_transfer(**c)
