import { ErrorBoundary } from "./components/ErrorBoundary";
import { DrivePage } from "./pages/DrivePage";

export default function App() {
  // Last resort: if the whole console fails to render, show the error instead
  // of a blank page.
  return (
    <ErrorBoundary label="Console">
      <DrivePage />
    </ErrorBoundary>
  );
}
