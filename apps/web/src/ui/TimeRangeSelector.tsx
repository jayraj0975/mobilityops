import { TIME_OPTIONS, type TimeSelector } from "../pune/types";

/** NOW, -15m, -1h, -6h, TODAY and FORECAST as one radio group (arrow keys move between them). */
export function TimeRangeSelector({
  value,
  onChange,
}: {
  value: TimeSelector;
  onChange: (v: TimeSelector) => void;
}) {
  return (
    <fieldset className="segmented">
      <legend className="sr-only">Time</legend>
      {TIME_OPTIONS.map((o) => (
        <label key={o.id} className={value === o.id ? "seg seg-on" : "seg"} title={o.hint}>
          <input type="radio" name="time" value={o.id} checked={value === o.id} onChange={() => onChange(o.id)} />
          <span>{o.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
