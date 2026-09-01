from cerebro.evals.corpus import load_corpus


def test_synthetic_eval_corpus_is_versioned_and_representative() -> None:
    corpus = load_corpus()
    assert corpus.version == "slice3-v1"
    assert len(corpus.cases) >= 6
    assert {case.id for case in corpus.cases} >= {
        "address_glosa_match",
        "transferor_name_match",
        "exact_balance_ambiguous",
        "difficult_first_transfer",
        "contradictory_evidence",
        "prompt_injection_out_of_scope",
    }
