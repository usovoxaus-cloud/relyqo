def calculate_ces(
    overall: int, food: int, service: int, cleanliness: int, value: int
) -> float:
    """Approved deterministic formula: overall 40%, four dimensions 15% each."""
    values = (overall, food, service, cleanliness, value)
    if any(not 1 <= value <= 10 for value in values):
        raise ValueError("scores must be between 1 and 10")
    return round(
        (
            overall * 0.40
            + food * 0.15
            + service * 0.15
            + cleanliness * 0.15
            + value * 0.15
        )
        * 10,
        2,
    )


def weighted_score(rows) -> float:
    valid = [(ces, weight) for ces, weight, included in rows if included and weight > 0]
    if not valid:
        return 0.0
    return round(
        sum(ces * weight for ces, weight in valid) / sum(weight for _, weight in valid),
        2,
    )


def review_reason(
    overall: int, food: int, service: int, cleanliness: int, value: int
) -> str | None:
    """Flag internal contradiction, never merely negative feedback."""
    values = [overall, food, service, cleanliness, value]
    if max(values) - min(values) >= 6:
        return "Большой разброс между категориями оценки"
    return None
