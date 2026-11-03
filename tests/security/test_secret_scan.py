"""Seeded credential detection and privacy-safe diagnostic regressions."""

from .secret_scan import find_secret_literals


def test_fixed_policy_labels_and_bound_hashes_are_not_credentials() -> None:
    source = (
        "RULE = 'EXACT_CURRENT_SOURCE_AUTHORITY_AND_NATIVE_BINDING_REQUIRED'\n"
        "FORMAT_SHA256 = '" + "ab" * 32 + "'\n"
        "ref = {'sha256': '" + "cd" * 32 + "'}\n"
        "schema = 'EXACT_REVIEWED_native_source_contract_v1_UNAPPROVED'\n"
        "rule = 'two-new-columns-four-blank-tail-styles-v1'\n"
        "value = data.get('exact_UTF8_hash_required_for_downstream_readback')\n"
    )
    assert find_secret_literals(source) == []


def test_token_patterns_are_detected_even_in_docstrings_or_test_named_literals() -> None:
    value = "123~" + "test" + "aB9_" * 12
    for source in [f"token = {value!r}", f'"""Never log {value}"""']:
        findings = find_secret_literals(source)
        assert findings and findings[0].kind == "credential format"
        assert value not in repr(findings)


def test_opaque_literals_and_sensitive_assignments_are_still_detected() -> None:
    for source in [
        "value = '" + "c9fA" * 15 + "'",
        "value = '" + "ab" * 32 + "'",
        "api_token = 'REAL_CREDENTIAL_MUST_NOT_BE_HIDDEN_BY_SYMBOL_CLASSIFICATION'",
        "access = 'sk-live-" + "x9A" * 14 + "'",
    ]:
        assert find_secret_literals(source)


def test_context_does_not_reveal_literal_or_source_text() -> None:
    literal = "UNIQUEprivateCredential" * 3
    findings = find_secret_literals(f"api_token = {literal!r}")
    assert findings
    assert literal not in repr(findings)
    assert all(finding.line == 1 for finding in findings)
