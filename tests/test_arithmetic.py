from app.arithmetic import calculate_expression


def test_basic_expression_is_deterministic():
    assert calculate_expression("1+4-3+7=?") == "Kết quả là 9."


def test_parentheses_are_supported():
    assert calculate_expression("2 * (3 + 4)") == "Kết quả là 14."


def test_natural_language_is_not_evaluated():
    assert calculate_expression("xin chào") is None
