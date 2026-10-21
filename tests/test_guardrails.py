from gateway.security.guardrails import check_citations


def test_valid_citations_in_first_cited_order() -> None:
    check = check_citations("Leave is 22 days [S2]. Sick leave is 10 days [S1][S2].", 3)
    assert check.valid_indices == [1, 0]
    assert check.grounded


def test_grouped_and_lowercase_markers() -> None:
    assert check_citations("Both apply [S1, S3] and [s2].", 3).valid_indices == [0, 2, 1]


def test_out_of_range_labels_are_invalid() -> None:
    check = check_citations("Made up [S9].", 3)
    assert check.valid_indices == []
    assert check.invalid_labels == ["S9"]
    assert not check.grounded


def test_no_citations_is_not_grounded() -> None:
    assert not check_citations("I don't have information about that.", 5).grounded


def test_zero_label_is_invalid() -> None:
    assert not check_citations("[S0]", 5).grounded
