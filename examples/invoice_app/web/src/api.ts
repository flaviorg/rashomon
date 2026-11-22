export async function fetchInvoices(params: Record<string, string>) {
  const res = await fetch("/invoices?" + new URLSearchParams(params));
  return res.json();
}
