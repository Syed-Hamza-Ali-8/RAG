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


# Lenticular brackets (U+3010/U+3011): gpt-oss's native citation style, observed in the
# refused benchmark answer for "When is the ISO 27001 recertification audit?".
OBSERVED_GPT_OSS = "The audit will take place from **15\u202fto\u202f19\u202fFebruary\u202f2027**【S1】【S3】"


def test_observed_lenticular_answer_is_grounded_and_normalised() -> None:
    check = check_citations(OBSERVED_GPT_OSS, 6)
    assert check.valid_indices == [0, 2]
    assert check.grounded
    assert check.normalized_text.endswith("**[S1][S3]")


def test_lenticular_whitespace_variants() -> None:
    check = check_citations("A 【 S2 】 and B 【s1】.", 3)
    assert check.valid_indices == [1, 0]
    assert check.normalized_text == "A [S2] and B [S1]."


def test_mixed_bracket_styles_in_one_answer() -> None:
    check = check_citations("Leave is 22 days [S2]. Sick leave is 10 days 【S1】 [ S2 ].", 3)
    assert check.valid_indices == [1, 0]
    assert check.normalized_text == "Leave is 22 days [S2]. Sick leave is 10 days [S1] [S2]."


def test_grouped_square_brackets_normalise_to_separate_markers() -> None:
    assert check_citations("Both apply [S1, S3].", 3).normalized_text == "Both apply [S1][S3]."


def test_lenticular_out_of_range_is_still_refused() -> None:
    check = check_citations("Made up 【S9】.", 3)
    assert not check.grounded
    assert check.invalid_labels == ["S9"]
    assert check.rejected_count == 1


def test_counts_valid_and_rejected() -> None:
    check = check_citations("[S1] 【S2】 [S7] 【S8】 [S1]", 3)
    assert check.valid_indices == [0, 1]
    assert check.invalid_labels == ["S7", "S8"]
    assert check.rejected_count == 2


def test_unobserved_formats_are_not_accepted() -> None:
    # Mismatched or other bracket styles were never observed; they must not count as citations.
    for text in ("Fact [S1】.", "Fact 【S1].", "Fact (S1).", "Fact {S1}.", "Fact S1.", "Fact 【S1, S2】."):
        assert not check_citations(text, 3).grounded, text


def test_text_without_citations_is_unchanged() -> None:
    text = "I don't have information about that in the documents I can access."
    assert check_citations(text, 6).normalized_text == text
