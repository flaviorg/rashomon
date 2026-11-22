from dataclasses import dataclass

from app.db import query
from app.models import Invoice


@dataclass
class InvoiceFilter:
    status: str | None = None
    customer_id: int | None = None


def filter_invoices(flt: InvoiceFilter, page: int = 1, per_page: int = 50) -> list[Invoice]:
    sql = "SELECT * FROM invoices WHERE 1=1"
    params = []
    if flt.status:
        sql += " AND status = ?"
        params.append(flt.status)
    if flt.customer_id:
        sql += " AND customer_id = ?"
        params.append(flt.customer_id)
    sql += " ORDER BY issued_on DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]
    return [Invoice(**row) for row in query(sql, params)]


def get_invoice(invoice_id: int) -> Invoice:
    return Invoice(**query("SELECT * FROM invoices WHERE id = ?", [invoice_id])[0])
