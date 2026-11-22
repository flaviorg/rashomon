import { formatCents } from "../money";
import { InvoiceFilters, Filters } from "./InvoiceFilters";

export function InvoiceTable({ rows, filters, onFilter }: { rows: Invoice[]; filters: Filters; onFilter: (f: Filters) => void }) {
  return (
    <section>
      <header>
        <h1>Invoices</h1>
        <InvoiceFilters value={filters} onChange={onFilter} />
      </header>
      <table>
        <thead>
          <tr><th>Number</th><th>Customer</th><th>Status</th><th>Issued</th><th>Amount</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}><td>{r.number}</td><td>{r.customerName}</td><td>{r.status}</td><td>{r.issuedOn}</td><td>{formatCents(r.amountCents)}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
