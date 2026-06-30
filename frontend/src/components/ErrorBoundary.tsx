import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * Last-line error boundary so an unexpected render error becomes a designed state, never a blank
 * white screen (CLAUDE.md §9 "every state designed ... none left as a raw browser error").
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Console only — never log document content (CLAUDE.md §10); this is a UI render error.
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="flex min-h-full items-center justify-center p-6">
          <div
            role="alert"
            className="max-w-md space-y-3 rounded-xl border border-verdict-rejected/40 bg-verdict-rejected-soft p-6 text-center"
          >
            <p className="text-lg font-semibold text-verdict-rejected">Something went wrong</p>
            <p className="text-sm text-text-secondary">
              The console hit an unexpected error and stopped to avoid showing an inconsistent state.
            </p>
            <pre className="overflow-auto rounded bg-black/30 p-2 text-left text-xs text-text-tertiary">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-md border border-accent/50 bg-accent/10 px-4 py-2 text-sm font-medium text-accent hover:bg-accent/20"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
