import { useCallback, useEffect, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** Run an async loader when ``deps`` change; cancels the request when they change or on unmount. */
export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const ctl = new AbortController();
    setState((s) => ({ data: s.data, loading: true }));
    loader(ctl.signal)
      .then((data) => {
        if (!ctl.signal.aborted) setState({ data, loading: false });
      })
      .catch((error: unknown) => {
        if (ctl.signal.aborted) return;
        setState({
          error: error instanceof Error ? error : new Error(String(error)),
          loading: false,
        });
      });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data: state.data, error: state.error, loading: state.loading, reload };
}
