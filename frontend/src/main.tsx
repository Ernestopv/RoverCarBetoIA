import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted variable fonts (no external CDN: the rover console may run on a
// field network without internet access).
import "@fontsource-variable/overpass";
import "@fontsource-variable/overpass-mono";

import App from "./App";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element #root was not found");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
