from dataclasses import dataclass
from datetime import date


@dataclass
class Customer:
    __tablename__ = "customers"

    id: int
    name: str
    email: str


@dataclass
class Invoice:
    __tablename__ = "invoices"

    id: int
    customer_id: int
    number: str
    status: str  # draft | sent | paid | void
    issued_on: date
    due_on: date
    amount_cents: int
    currency: str = "USD"
