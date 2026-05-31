from main import add


def test_add_default():
    assert add(1, 2) == 3


def test_add_subtract_mode():
    assert add(5, 2, mode="sub") == 3
    assert add(5, 2, mode="subtract") == 3
