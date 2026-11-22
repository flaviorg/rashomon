from app.money import format_cents


def test_format_cents():
    assert format_cents(1234550) == "$12,345.50"
