/**
 * Renders a formatted money string with the fractional part visually dimmed,
 * e.g. "$1,284.52" becomes $1,284 followed by a muted ".52".
 */
export function DisplayAmount({ value }: { value: string }) {
  const match = value.match(/^(.*?)([.,]\d{1,2})$/);
  if (!match) return <>{value}</>;
  return (
    <>
      {match[1]}
      <span className="amount-cents">{match[2]}</span>
    </>
  );
}
