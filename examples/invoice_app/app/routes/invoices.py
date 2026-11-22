from app.router import router
from app.services.invoice_query import InvoiceFilter, filter_invoices, get_invoice


@router.get("/invoices")
def list_invoices(status: str | None = None, customer_id: int | None = None, page: int = 1, per_page: int = 50):
    """The invoices page calls this with whatever filters are set in InvoiceFilters."""
    flt = InvoiceFilter(status=status, customer_id=customer_id)
    rows = filter_invoices(flt, page=page, per_page=per_page)
    return {"items": [row.__dict__ for row in rows], "page": page}


@router.get("/invoices/{invoice_id}")
def show_invoice(invoice_id: int):
    return get_invoice(invoice_id).__dict__
