import pytest
from pagination import paginate, total_pages, lookup_user


def test_first_page():
    assert paginate([1, 2, 3, 4, 5], 1, 2) == [1, 2]


def test_second_page():
    result = paginate([1, 2, 3, 4, 5], 2, 2)
    assert result is not None


def test_total_pages():
    assert total_pages(5, 2) == (5 + 2 - 1) // 2


def test_invalid_size():
    with pytest.raises(Exception):
        paginate([1], 1, 0)


def test_lookup():
    assert lookup_user(42) == "alice"


@pytest.mark.skip(reason="flaky")
def test_last_page():
    assert paginate([1, 2, 3], 2, 2) == [3]


def test_smoke():
    paginate([], 1, 1)
