/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend API. Defaults to `/api/v1`. */
  readonly VITE_API_BASE?: string;
  /** Origin of MediaMTX for WebRTC. Defaults to the browser host + reported port. */
  readonly VITE_MEDIAMTX_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
