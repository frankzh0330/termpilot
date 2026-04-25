from calc import add, multiply


def test_add():
    assert add(1, 2) == 3
    assert add(-1, 1) == 0


def test_multiply():
    assert multiply(2, 3) == 6
