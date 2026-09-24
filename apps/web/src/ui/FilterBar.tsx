export interface FilterDef {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
}

/** A row of labelled selects. Values are strings; "" means "any". */
export function FilterBar({
  filters,
  onChange,
}: {
  filters: FilterDef[];
  onChange: (id: string, value: string) => void;
}) {
  return (
    <form className="filterbar" onSubmit={(e) => e.preventDefault()} aria-label="Filters">
      {filters.map((f) => (
        <label key={f.id}>
          {f.label}
          <select value={f.value} onChange={(e) => onChange(f.id, e.target.value)}>
            {f.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      ))}
    </form>
  );
}
