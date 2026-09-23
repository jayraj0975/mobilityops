import { Component, type ReactNode } from "react";

/** A malformed response must produce a readable error, never a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" className="notice notice-error">
          <strong>This section could not be displayed</strong>
          <p>The data received did not have the expected shape ({this.state.error.message}).</p>
          <button type="button" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
