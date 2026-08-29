import pytest
from app.score import calculate_ces, weighted_score


def test_ces_formula():
    assert calculate_ces(10, 8, 8, 8, 8) == 88.0


def test_weighted_score():
    assert weighted_score([(80, 1, True), (100, 0.5, True)]) == 86.67


def test_excluded_rating():
    assert weighted_score([(80, 1, True), (0, 1, False)]) == 80


def test_empty_score():
    assert weighted_score([]) == 0


def test_range_validation():
    with pytest.raises(ValueError):
        calculate_ces(11, 8, 8, 8, 8)
