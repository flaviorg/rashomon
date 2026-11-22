export type Filters = { status?: string; customerId?: number };

export function InvoiceFilters({ value, onChange }: { value: Filters; onChange: (f: Filters) => void }) {
  return (
    <form>
      <select value={value.status ?? ""} onChange={(e) => onChange({ ...value, status: e.target.value || undefined })}>
        <option value="">All statuses</option>
        <option value="sent">Sent</option>
        <option value="paid">Paid</option>
      </select>
    </form>
  );
}
