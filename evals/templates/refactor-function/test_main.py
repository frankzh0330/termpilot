from main import add


def test_add():
    assert add(1, 2) == 3


def test_add_subtract():
    assert add(5, 3, mode="sub") == 2
    assert add(10, 4, mode="subtract") == 6
