# Frontend (React + TypeScript + Vite)

```bash
npm install
npm run dev      # http://localhost:5173 (proxy /api -> http://127.0.0.1:8000)
npm run build    # type-check + production build in dist/
```

The backend must be running (`ROVER_MODE=simulator` by default).

Optional: override the API base URL with `VITE_API_BASE` (default `/api/v1`).
