# Architecture

Diagrams are written as **Mermaid**: they render on GitHub/GitLab and stay in
version control as text. Update them when the architecture changes significantly
(`AGENTS.md` §22).

## 1. System architecture

```mermaid
flowchart TB
    subgraph Client
        UI["React + TypeScript + Vite<br/>web / tablet console"]
    end

    subgraph Backend["Python / FastAPI"]
        API["API routes (/api/v1)<br/>REST + WebSocket"]
        RoverSvc["RoverService<br/>watchdog + orchestration"]
        Safety["SafetyLayer<br/>validation + limits"]
        CamAI["Camera / AI<br/>detection · pose · tracking"]
        Telemetry["TelemetryService"]
    end

    subgraph Transport
        Mtx["MediaMTX<br/>RTSP in → WebRTC/WHEP out"]
    end

    subgraph Hardware
        Cam["Raspberry Pi AI Camera<br/>Sony IMX500"]
        Chassis["WAVE ROVER base<br/>motor controller"]
        Motors["4WD motors"]
    end

    UI -- "HTTP / WebSocket" --> API
    API --> RoverSvc
    RoverSvc --> Safety
    API --> CamAI
    API --> Telemetry

    Cam -- "RTSP" --> Mtx
    Mtx -- "WebRTC (WHEP)" --> UI

    Safety -- "Wi-Fi / TCP-IP" --> Chassis
    Chassis --> Motors
```

**Key principle:** the frontend never touches the hardware. Every motion command
goes `API → RoverService → SafetyLayer → driver → Wi-Fi → WAVE ROVER`.

## 2. Motion control path

```mermaid
flowchart LR
    Input["Joystick / arrow keys<br/>+ throttle"] --> Move["POST /rover/move"]
    Move --> Validate["RoverService<br/>normalize + arm watchdog"]
    Validate --> Clamp["SafetyLayer<br/>clamp to limits"]
    Clamp --> Driver["Rover implementation"]
    Driver --> Sim["WaveRoverSimulator"]
    Driver --> Wifi["WaveRoverWifiDriver"]
    Wifi -- "Wi-Fi" --> Chassis["WAVE ROVER"]
```

Stop is redundant on purpose: releasing the joystick, the Space key, the backend
watchdog, and `POST /rover/stop`.

## 3. Live-video and AI pipeline

```mermaid
flowchart LR
    Cam["Picamera2 / simulator"] -- "RTSP" --> Mtx["MediaMTX"]
    Mtx -- "WebRTC (WHEP)" --> Video["&lt;video&gt; in React"]
    Cam -- "on-sensor inference" --> AI["detection / pose"]
    AI --> Track["tracking"] --> WS["/ai/stream (WebSocket)"]
    WS --> Overlay["boxes / skeletons overlay"]
```

Nothing is recorded: frames and detections live only in memory and are replaced
by the next result. See `docs/specs/live-video.md` and `docs/specs/ai-detection.md`.
