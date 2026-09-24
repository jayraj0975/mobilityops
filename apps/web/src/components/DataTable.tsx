import type { ReactNode } from "react";

export interface Column<R> {
  key: string;
  header: string;
  render: (row: R) => ReactNode;
  numeric?: boolean;
}

export function DataTable<R>({
  caption,
  columns,
  rows,
  rowKey,
}: {
  caption: string;
  columns: Column<R>[];
  rows: R[];
  rowKey: (row: R) => string;
}) {
  return (
    // A wide table scrolls sideways; keyboard users must be able to focus it to scroll (WCAG 2.1.1).
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? "num" : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)}>
              {columns.map((c) => (
                <td key={c.key} className={c.numeric ? "num" : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
