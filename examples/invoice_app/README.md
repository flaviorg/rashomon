# invoice_app (sample repo for rashomon)

A tiny invoicing app used by `rashomon demo`. It is not meant to run: it exists so the
grounding step has real routes, tables, services and components to point at.

- `app/routes/invoices.py`: `GET /invoices` (filterable list) and `GET /invoices/{invoice_id}`
- `app/services/invoice_query.py`: the filter logic behind the list
- `app/money.py`: cents to display strings
- `app/jobs/__init__.py`: a minimal background queue
- `db/schema.sql`: `customers` and `invoices` tables
- `web/src/components/`: the invoices page (`InvoiceTable`, `InvoiceFilters`)
