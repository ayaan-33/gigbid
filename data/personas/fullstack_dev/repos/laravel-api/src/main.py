import pytest


@pytest.mark.parametrize("value,expected", [(0, 0), (10, 10)])
def test_identity(value, expected):
    assert value == expected
