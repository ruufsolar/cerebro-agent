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
