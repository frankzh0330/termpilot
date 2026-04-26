from app import greet


def test_greet():
    assert greet("world") == "Hello, World!"
    assert greet("  hello  ") == "Hello, Hello!"
