"""Retain the input bounds required by the DNS and trace-context advisories."""

from types import SimpleNamespace

import dns.exception
import dns.rdata
import pytest
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace.propagation import tracecontext

TRACEPARENT = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"


@pytest.mark.parametrize("service", ["-1", "65536"])
def test_wks_rejects_service_numbers_outside_wire_range(service: str) -> None:
    """CVE-2026-128089: reject out-of-range bitmap offsets before allocation."""
    with pytest.raises(dns.exception.SyntaxError):
        dns.rdata.from_text("IN", "WKS", f"192.0.2.1 udp {service}")


@pytest.mark.parametrize("service", ["0", "65535"])
def test_wks_accepts_wire_range_endpoints(service: str) -> None:
    value = dns.rdata.from_text("IN", "WKS", f"192.0.2.1 udp {service}")
    assert value.to_text() == f"192.0.2.1 17 {service}"


@pytest.mark.parametrize(
    "suffix", [" " * 458, " " * 458 + "\ninvalid"], ids=["spaces", "newline"]
)
def test_oversized_traceparent_is_rejected_before_regex(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    """CVE-2026-126360: enforce the 512-character cap before regex parsing."""

    def forbidden_search(*args: object, **kwargs: object) -> None:
        raise AssertionError("Oversized traceparent reached regex parsing")

    monkeypatch.setattr(tracecontext, "re", SimpleNamespace(search=forbidden_search))
    context = Context()
    assert len(TRACEPARENT + suffix) > 512
    assert (
        tracecontext.TraceContextTextMapPropagator().extract(
            {"traceparent": TRACEPARENT + suffix}, context=context
        )
        is context
    )


def test_bounded_traceparent_still_extracts_remote_context() -> None:
    context = tracecontext.TraceContextTextMapPropagator().extract(
        {"traceparent": TRACEPARENT}
    )
    span = trace.get_current_span(context).get_span_context()
    assert span.is_valid and span.is_remote
    assert span.trace_id == int("0123456789abcdef0123456789abcdef", 16)
    assert span.span_id == int("0123456789abcdef", 16)
