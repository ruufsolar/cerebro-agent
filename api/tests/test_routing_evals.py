from cerebro.agent.models import RequestKind
from cerebro.evals.routing import grade_routes, load_routing_corpus


def test_routing_corpus_covers_required_categories_and_passes_exact_results() -> None:
    corpus = load_routing_corpus()
    actual = {case.id: case.expected for case in corpus.cases}

    report = grade_routes(corpus, actual)

    assert len(corpus.cases) >= 12
    assert {case.expected for case in corpus.cases} == set(RequestKind)
    assert any(case.prior_thread for case in corpus.cases)
    assert sum(case.has_triggering_image for case in corpus.cases) >= 2
    assert report["passed"] is True
    assert report["payment_to_general"] == []


def test_routing_gate_has_zero_tolerance_for_payment_to_general() -> None:
    corpus = load_routing_corpus()
    actual = {case.id: case.expected for case in corpus.cases}
    actual["explicit_payment"] = RequestKind.GENERAL

    report = grade_routes(corpus, actual)

    assert report["passed"] is False
    assert report["payment_to_general"] == ["explicit_payment"]


def test_routing_gate_checks_clarification_and_topic_changes() -> None:
    corpus = load_routing_corpus()
    actual = {case.id: case.expected for case in corpus.cases}
    clarifications = {case.id: case.clarify for case in corpus.cases}
    assert grade_routes(corpus, actual, clarifications)["passed"]
    clarifications["vague_without_context"] = False
    report = grade_routes(corpus, actual, clarifications)
    assert not report["passed"]
    assert report["clarification_mismatches"] == ["vague_without_context"]
