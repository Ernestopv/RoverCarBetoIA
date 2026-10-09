import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  /** Area name, used in the fallback so the operator knows what failed. */
  label: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Isolates a failing panel.
 *
 * A crash while rendering the camera or the telemetry readouts must never take
 * down the drive controls: on a rover console the operator has to keep the
 * ability to stop the machine. Error boundaries are the one case where React
 * still requires a class component — there is no hook equivalent.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[${this.props.label}] render failed`, error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="alert" role="alert">
        <strong className="alert__title">{this.props.label} is unavailable</strong>
        <span className="alert__detail">{error.message}</span>
        <span className="alert__hint">The rest of the console keeps working.</span>
      </div>
    );
  }
}
