/**
 * Peso amounts, formatted the one way.
 *
 * The API sends decimals as strings, deliberately: JSON numbers are IEEE
 * doubles and ₱1,234.56 does not survive one exactly. So this parses for
 * display only -- nothing here is ever sent back or added up. Money
 * arithmetic belongs on the server, where it is Decimal.
 */
export function formatMoney(amount: string, currency = "PHP"): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return amount;
  return new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(value);
}
