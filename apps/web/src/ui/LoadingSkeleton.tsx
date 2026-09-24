/** A placeholder with the shape of what is loading, so the page does not jump. */
export function LoadingSkeleton({ lines = 3, height }: { lines?: number; height?: number }) {
  return (
    <div className="skeleton" role="status" aria-label="Loading" style={height ? { minHeight: height } : undefined}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton-line" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}
