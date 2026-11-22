def format_cents(amount_cents: int, currency: str = "USD") -> str:
    """1234550 -> '$12,345.50'. Used by the invoices page."""
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")
    return f"{symbol}{amount_cents / 100:,.2f}"
