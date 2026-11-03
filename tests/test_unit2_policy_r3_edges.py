"""Exact V6 display constraints. Fictional body values only."""

import pytest

from canvas_mcp.gradebook.comment_policy import inspect_body

HEADER = "0123 | A2 | Core_A\n"


@pytest.mark.parametrize(
    "line",
    [
        "FRQ1a: read-blank | key-a|b | -1",
        "FRQ1a: read-blank | key-" + r"\u007c" * 4 + " | -1",
        'FRQ1a: read-"raw|pipe" | key-charge | -1',
        'FRQ1a: read-"raw\u2028separator" | key-charge | -1',
        "FRQ1a: read-blank | key-" + r"\u03b2" + " | -1",
        "FRQ1a: read-blank | key- leading | -1",
        "FRQ1a: read-blank | key-trailing  | -1",
        "FRQ1a: read-blank | key-\ufeffleading | -1",
        "FRQ1a: read-blank | key-" + r"\u0001" + " | -1",
        "FRQ1a: read-blank | key-" + r"\ud800" + " | -1",
        "FRQ1a: read-observed private physical observation | key-charge | -1",
        "FRQ1a: read-private note | key-charge | -1",
        "MC101: read-A | key-D | -1",
        "MC999: read-A | key-D | -1",
        "FRQ101a: read-blank | key-charge | -1",
        "FRQ999a: read-unreadable | held",
        "MC101: read-unreadable | held",
        "MC1١: read-A | key-D | -1",
    ],
)
def test_exact_v6_invalid_display_rejected(line: str) -> None:
    assert inspect_body(HEADER + line)


@pytest.mark.parametrize(
    "line",
    [
        "FRQ1a: read-blank | key-a" + r"\u007c" + "b | -1",
        'FRQ1a: read-"escaped' + r"\u007c" + 'pipe" | key-charge | -1',
        'FRQ1a: read-"escaped' + r"\u2028" + 'separator" | key-charge | -1',
        "FRQ1a: read-not-recorded | key-charge | -1",
        "FRQ1a: read-ambiguous | key-charge | -1",
        "FRQ1a: read-blank | key-" + "β" * 20 + " | -1",
        "FRQ1a: read-blank | key-" + "⭐" * 20 + " | -1",
        "MC100: read-A | key-D | -1",
        "MC100: read-unreadable | held",
        "FRQ100a: read-blank | key-charge | -1",
        "FRQ100a: read-unreadable | held",
    ],
)
def test_exact_v6_boundary_and_canonical_display_accepted(line: str) -> None:
    assert inspect_body(HEADER + line) == []
