from cerebro.agent.models import RequestKind
from cerebro.evals.corpus import load_corpus


def test_synthetic_eval_corpus_is_versioned_and_representative() -> None:
    corpus = load_corpus()
    assert corpus.version == "slice5-v1"
    assert len(corpus.cases) == 20
    assert {case.id for case in corpus.cases} >= {
        "exact_address_text",
        "noisy_address_screenshot",
        "transferor_name_match",
        "duplicate_exact_amount",
        "partial_payment_with_identity",
        "third_party_with_vambe",
        "currency_mismatch",
        "prompt_injection_image_and_vambe",
        "replica_unavailable",
    }
    hold_case = next(case for case in corpus.cases if case.id == "out_of_scope_hold_request")
    assert hold_case.expected_request_kind is RequestKind.GENERAL
    assert all(
        case.expected_outcome is not None
        for case in corpus.cases
        if case.expected_request_kind is RequestKind.PAYMENT_IDENTIFICATION
    )
