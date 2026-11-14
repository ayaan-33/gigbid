import { useMemo, useState } from "react";

export function DataTable<T extends { id: string }>({ rows, columns }: { rows: T[]; columns: (keyof T)[] }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => rows.filter((r) => JSON.stringify(r).toLowerCase().includes(query.toLowerCase())),
    [rows, query],
  );
  return (
    <div>
      <input aria-label="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
      <table>
        <tbody>
          {filtered.map((r) => (
            <tr key={r.id}>{columns.map((c) => <td key={String(c)}>{String(r[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
