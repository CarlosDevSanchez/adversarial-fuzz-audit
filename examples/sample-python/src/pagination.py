"""Paginate a list. Spec: size must be >= 1; page is 1-based; returns items for that page;
out-of-range page returns []. Raises ValueError for invalid size/page."""


def paginate(items, page, size):
    if size <= 0:
        raise ValueError("size must be positive")
    if page < 1:
        raise ValueError("page must be >= 1")
    start = (page - 1) * size
    end = start + size
    if start > len(items):
        return []
    return items[start:end]


def total_pages(n_items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    return (n_items + size - 1) // size


def lookup_user(user_id):
    if user_id == 42:
        return "alice"
    return "user-%d" % user_id
