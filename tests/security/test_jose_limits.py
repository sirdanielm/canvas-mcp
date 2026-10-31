"""Exercise the JOSE boundary that the dependency security floor must retain."""

import pytest
from joserfc import jws
from joserfc.errors import ExceededSizeError
from joserfc.jwk import OctKey


class _SegmentsMustNotBeCopied(bytes):
    def split(self, sep: bytes | None = None, maxsplit: int = -1) -> list[bytes]:
        raise AssertionError("Oversized untrusted JWS reached segment copying")


def test_oversized_jws_is_rejected_before_segment_copying() -> None:
    """CVE-2026-119284: reject by total length before splitting input bytes."""
    registry = jws.JWSRegistry()
    registry.max_header_length = 16
    registry.max_payload_length = 16
    registry.max_signature_length = 16
    value = _SegmentsMustNotBeCopied(b"a" * 49)

    with pytest.raises(ExceededSizeError):
        jws.deserialize_compact(value, None, registry=registry)


def test_bounded_signed_jws_still_verifies() -> None:
    """The security patch must retain normal signature verification."""
    key = OctKey.import_key(b"a" * 32)
    token = jws.serialize_compact({"alg": "HS256"}, b"fictional payload", key)

    assert jws.deserialize_compact(token, key).payload == b"fictional payload"
