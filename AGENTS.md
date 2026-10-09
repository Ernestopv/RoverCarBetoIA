# AGENTS.md — RoverCarBeto

## 1. Project identity

**Project name:** RoverCarBeto

RoverCarBeto is a 4WD mobile robotics project that will be developed **from scratch**.

The goal is to build the rover using **AI as the primary development assistant**, while maintaining a clean, modular, documented, testable, and safe architecture.

AI may help design, program, test, document, debug, and evolve the project, but it must always respect the rules defined in this file.

---

## 2. General objective

Build a mobile rover based on a **Raspberry Pi 5** and a **Waveshare WAVE ROVER 4WD** chassis, with capabilities such as:

- Remote motion control.
- Web interface to drive the rover.
- API to control the vehicle.
- Live video.
- Telemetry.
- Battery status.
- Camera with AI processing.
- Object detection.
- Object tracking.
- Pose estimation when useful.
- Live video streaming only; do not record or persist images or video.
- Simulator for development without physical hardware.
- Deployment using Docker.
- Automated tests.
- Future evolution toward semi-autonomous and autonomous navigation.

The project must be developable first on a computer using simulation and later run on the Raspberry Pi 5.

---

## 3. Core principle

This project is developed **AI-first**, but not in an improvised way.

AI must act as a **senior software, robotics, and embedded systems engineer**.

Before making significant changes, it must:

1. Understand the requested objective.
2. Review the existing architecture.
3. Identify the affected files.
4. Propose the simplest solution that meets the objective.
5. Implement small, verifiable changes.
6. Add or update tests.
7. Run the available validations.
8. Update documentation when behavior changes.
9. Avoid introducing unnecessary dependencies.
10. Explain any relevant architectural decision.

AI must not rewrite large parts of the project unnecessarily.

---

## 4. Target hardware

The reference architecture includes:

- Raspberry Pi 5.
- Waveshare WAVE ROVER 4WD.
- Raspberry Pi AI Camera with a Sony IMX500 sensor.
- M.2 / PCIe adapter.
- SSD NVMe.
- Wi-Fi connectivity.
- WAVE ROVER integrated electronics for motor control.

### Communication with the motor base

The Raspberry Pi **will not control the motors directly through GPIO**.

The WAVE ROVER base has its own control electronics, and the Raspberry Pi will communicate with it **over Wi-Fi**, acting as the high-level controller.

Conceptual architecture:

```text
React Frontend
      │
      ▼
Python / FastAPI
      │
      ▼
Rover Service
      │
      ▼
WaveRover Network Client
      │
   Wi-Fi / TCP-IP
      │
      ▼
WAVE ROVER
Motor controller
      │
      ▼
4WD motors
```

Communication with the WAVE ROVER must be encapsulated in a dedicated backend layer.

Never scatter WAVE ROVER network calls across different application modules.

There must be an abstraction such as:

```text
Rover
 ├── WaveRoverWifiDriver
 └── WaveRoverSimulator
```

The real implementation will be responsible for:

- connecting to the WAVE ROVER base;
- sending commands;
- receiving responses and status;
- timeout handling;
- reconnection;
- connection-state validation;
- communication-loss detection;
- translating between internal commands and the actual WAVE ROVER protocol.

Do not assume that hardware is available during development.

Every hardware-dependent component should have, whenever reasonable:

- an abstract interface;
- a real implementation;
- a simulated or mock implementation.

---

## 5. Target architecture

The application must be divided into clearly separated components.

Conceptual architecture:

```text
                         ┌─────────────────────┐
                         │   React Frontend    │
                         │   Web / Tablet UI   │
                         └──────────┬──────────┘
                                    │
                         HTTP / WebSocket
                                    │
                         ┌──────────▼──────────┐
                         │   Python / FastAPI  │
                         │ Backend RoverCarBeto│
                         └───────┬──────┬──────┘
                                 │      │
                    ┌────────────┘      └────────────┐
                    │                                │
           ┌────────▼────────┐              ┌────────▼────────┐
           │ Camera / AI     │              │  Rover Service  │
           │ IMX500          │              │ Safety + State  │
           └────────┬────────┘              └────────┬────────┘
                    │                                │
              Video pipeline                 WaveRoverWifiDriver
                    │                                │
           ┌────────▼────────┐                    Wi-Fi
           │    MediaMTX     │                       │
           │     WebRTC      │              ┌────────▼────────┐
           └────────┬────────┘              │   WAVE ROVER    │
                    │                       │ Motor Controller│
                    ▼                       └────────┬────────┘
             React <video>                          │
                                                   ▼
                                              4WD motors
```

Separation of responsibilities:

```text
Frontend
    React + TypeScript

Backend
    Python + FastAPI

Video
    Picamera2 / IMX500 -> MediaMTX -> WebRTC -> React

Rover control
    FastAPI -> Rover Service -> WaveRoverWifiDriver -> Wi-Fi -> WAVE ROVER
```

React must not access the hardware or motor base directly.

All motion control must pass through:

```text
React
  ↓
FastAPI
  ↓
Rover Service
  ↓
Safety Layer
  ↓
WaveRoverWifiDriver
  ↓
Wi-Fi
  ↓
WAVE ROVER
```

This architecture may evolve, but the separation between interface, logic, safety, network transport, and hardware must be preserved.

## 6. Recommended project structure

AI should evolve the project toward a structure similar to this:

```text
RoverCarBeto/
│
├── AGENTS.md
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
│
├── app/
│   ├── api/
│   │   ├── routes/
│   │   └── schemas/
│   │
│   ├── rover/
│   │   ├── interface.py
│   │   ├── service.py
│   │   ├── safety.py
│   │   ├── wave_rover_wifi.py
│   │   ├── simulator.py
│   │   └── models.py
│   │
│   ├── camera/
│   │   ├── interface.py
│   │   ├── imx500.py
│   │   ├── simulator.py
│   │   ├── stream.py
│   │   ├── health.py
│   │   └── factory.py
│   │
│   ├── ai/
│   │   ├── detection.py
│   │   ├── tracking.py
│   │   ├── pose.py
│   │   ├── broadcast.py
│   │   └── models.py
│   │
│   ├── telemetry/
│   │   └── service.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   │
│   └── main.py
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── types/
│   │   └── App.tsx
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── static/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── diagrams/
│
├── scripts/
│
├── docker/
│
├── Dockerfile
├── docker-compose.yml
│
└── .github/
    └── workflows/
```

It is not mandatory to migrate to this structure immediately if there is prior code. Changes must be made gradually.

---

## 7. Preferred technology stack

Prefer:

### Backend

The backend will be developed in **Python**.

Preferred stack:

- Python 3.12 or a version compatible with Raspberry Pi.
- FastAPI for the HTTP API.
- Pydantic for models, validation, and configuration.
- Uvicorn as the ASGI server.
- `httpx` for HTTP communications.
- Use async code only when it provides a real advantage.

The backend will be responsible for:

- rover control;
- hardware access;
- simulation;
- camera;
- AI processing;
- telemetry;
- safety logic;
- the API consumed by the frontend.

### Frontend

The frontend will be developed in **React**.

Preferred stack:

- React.
- TypeScript.
- Vite.
- Simple CSS or CSS Modules.
- `fetch` or a lightweight API-consumption layer.

The frontend will be responsible for:

- control panel;
- joystick or motion controls;
- stop control (release-to-stop, the Space key, and the backend watchdog);
- video display;
- telemetry;
- battery;
- connection status;
- computer-vision results;
- configuration exposed to the user.

Avoid adding large frontend frameworks or global state libraries unless there is a real need.

### Infrastructure

- Docker.
- Docker Compose.
- Nginx.
- Environment variables for configuration.

The project will not use CI/CD, Git, or formal separation into development, QA, or production environments.

### Tests

Prefer:

- pytest.
- pytest-asyncio when necessary.
- mocks only where there is an external or hardware dependency.

---

## 8. Development without hardware

This is a critical rule.

**The project must be runnable and testable without the physical rover.**

AI must preserve this capability.

There must be a mode such as:

```env
ROVER_MODE=simulator
CAMERA_MODE=simulator
```

and a real mode:

```env
ROVER_MODE=hardware
CAMERA_MODE=imx500
```

Business logic must not depend directly on hardware.

Conceptual example:

```python
class Rover:
    async def move(self, linear: float, angular: float) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def status(self) -> RoverStatus:
        ...
```

Implementations may be:

```text
WaveRoverWifiDriver
WaveRoverSimulator
```

but both must respect the same contract.

---


### Wi-Fi communication with WAVE ROVER

The Wi-Fi connection to the motor base is considered a critical dependency.

The backend must treat it as an external resource that can fail at any time.

Rules:

- Use timeouts for every network operation.
- Never block indefinitely while waiting for a rover response.
- Maintain an explicit connection state.
- Detect disconnections.
- Attempt reconnection in a controlled manner.
- Avoid aggressive reconnection loops.
- Log latency and communication errors.
- Do not assume that sending a command means it was executed.
- If the protocol returns acknowledgment or status, use it.
- Clearly separate connection, transport, protocol, and motion logic.
- Do not expose WAVE ROVER protocol details directly through the HTTP API.
- The IP, port, and other communication parameters must come from configuration.
- Do not hard-code fixed IP addresses directly into application logic.

Expected configuration variables:

```env
WAVE_ROVER_HOST=192.168.x.x
WAVE_ROVER_PORT=xxxx
WAVE_ROVER_TIMEOUT=1.0
```

The actual values must be adjusted to the connection mode and protocol defined by the official WAVE ROVER documentation.


## 9. Rover safety

Any code related to motion is considered critical.

AI must prioritize physical safety over any other functionality.

Mandatory rules:

- A STOP command must exist.
- STOP must take priority over any other command.
- On a serious exception, the rover must attempt to stop.
- If control connectivity is lost, there must be a safe-stop mechanism.
- Loss of the Wi-Fi link between the Raspberry Pi and WAVE ROVER must be considered a critical condition.
- The system must maintain a watchdog or equivalent mechanism whenever the protocol/hardware allows it.
- Never keep a motion command active indefinitely if communication is lost.
- Do not allow speeds without explicit limits.
- Validate all motion parameters.
- Do not assume that a successful HTTP request means the rover actually moved correctly.
- Log communication errors.
- Avoid motion loops without timeouts.
- Never trigger physical motion automatically during tests.

For any autonomous behavior:

```text
Perception -> Decision -> Safety validation -> Motion
```

Never:

```text
AI -> motors directly
```

---

## 10. API

The API must be consistent and versionable.

Example:

```text
/api/v1/health
/api/v1/rover/status
/api/v1/rover/move
/api/v1/rover/stop
/api/v1/telemetry
/api/v1/camera/status
/api/v1/ai/detections
```

Endpoints that generate motion must strictly validate inputs.

Conceptual example:

```json
{
  "linear": 0.5,
  "angular": -0.2
}
```

Values must be normalized or limited according to the implementation.

---

### Camera storage policy

RoverCarBeto uses the camera only for:

```text
live video streaming
real-time AI inference
real-time detections
```

Camera media must remain ephemeral.

```text
Camera -> processing / inference -> WebRTC -> browser
```

Not:

```text
Camera -> files -> storage
```

No feature should write camera frames, images, clips, or recordings to disk unless this requirement is explicitly changed in the future.

## 10.1. Video streaming

The official video architecture for the project will be:

```text
Raspberry Pi AI Camera IMX500
          │
       Picamera2
          │
          ├── IMX500 inference -> Python
          │
          └── video -> MediaMTX -> WebRTC -> React
```

Rules:

- Use WebRTC for real-time video.
- Use MediaMTX as the streaming server/intermediary.
- The camera is for **live streaming and real-time AI inference only**.
- Do **not** record video.
- Do **not** save camera images or snapshots to disk.
- Do **not** implement image galleries, recording history, video archives, or playback.
- Avoid transporting video frame-by-frame through FastAPI.
- FastAPI will handle control, status, telemetry, and AI integration.
- AI detections may be sent to the frontend via WebSocket or API.
- The frontend will display video using a WebRTC-compatible `<video>` element.
- Video frames may exist temporarily in memory as required for streaming or inference, but must not be persisted.

## 11. AI and computer vision

AI functions must remain decoupled from physical control.

Recommended pipeline:

```text
Camera
   ↓
Frame
   ↓
Detector
   ↓
Detections
   ↓
Tracker
   ↓
World / Scene State
   ↓
Decision Layer
   ↓
Safety Layer
   ↓
Rover Controller
```

Possible capabilities:

- person detection;
- vehicle detection;
- obstacle detection;
- object tracking;
- pose estimation;
- person following;
- traversable-area recognition;
- assisted navigation;
- future autonomous navigation.

Each module must be independently testable.

---

## 12. Using AI to develop code

When an AI agent receives a task, it must follow this process.

### Step 1 — Analyze

Determine:

- what the user wants;
- which part of the system it affects;
- which current behavior could break;
- which tests exist.

### Step 2 — Plan

For changes affecting multiple files, prepare a short plan first.

Example:

```text
1. Create Rover interface.
2. Adapt the existing driver.
3. Add simulator.
4. Update API.
5. Add tests.
6. Run the suite.
```

### Step 3 — Implement

Make the minimum necessary change.

Avoid:

- premature abstractions;
- unnecessary patterns;
- dependencies that add no value;
- large cosmetic changes mixed with functional changes.

### Step 4 — Verify

Whenever possible, run:

```bash
pytest
```

and the tools configured in the project, for example:

```bash
ruff check .
ruff format --check .
mypy .
```

Do not claim that tests pass if they have not been run.

### Step 5 — Document

Update README, diagrams, examples, or comments if public behavior changes.

---

## 13. Code conventions

### Python

- Follow PEP 8.
- Use type hints.
- Prefer small functions.
- Prefer clear names over explanatory comments.
- Avoid functions with too many responsibilities.
- Avoid mutable global state.
- Use `pathlib` for paths when reasonable.
- Use `logging`, not `print`, for application logs.

Example:

```python
logger.info("Rover connected")
```

Not:

```python
print("connected")
```

---

## 14. Configuration

Configuration must be defined through environment variables when necessary.

Never commit to Git:

- passwords;
- private keys;
- tokens;
- Wi-Fi credentials;
- secrets;
- private endpoints containing credentials.

Keep only this example file:

```text
.env.example
```

Do not create variants such as `.env.dev.example`, `.env.qa.example`, or `.env.prod.example` unless explicitly requested.

The `.env.example` file must never contain real secrets.

---

## 15. Logging and observability

Logs must make it possible to diagnose:

- rover connection;
- camera connection;
- motion commands;
- STOP;
- HTTP errors;
- battery;
- latency;
- simulator errors;
- inference errors;
- AI model status.

Avoid continuously storing unnecessary information.

Messages must include enough context for diagnosis.

---

## 16. Telemetry

Design telemetry as an independent module.

Potential data:

```text
timestamp
battery_voltage
battery_percentage
linear_speed
angular_speed
wifi_signal
rover_latency
cpu_temperature
cpu_usage
memory_usage
disk_usage
camera_fps
ai_inference_ms
```

Do not assume that all sensors will be available.

Optional fields must be handled correctly.

---

## 17. Persistence

The project does **not** persist camera images or video.

The local SSD may be used only for data that is useful to the application, such as:

- telemetry;
- logs;
- application data;
- AI models.

The following must not be stored:

- recorded video;
- camera snapshots;
- live frame processingd images;
- video archives;
- camera history.

The application must define storage limits for telemetry, logs, and other persistent data.

Prevent logs or telemetry from filling the disk indefinitely.

## 18. Docker

The project should be runnable through Docker Compose whenever possible.

Approximate target:

```bash
docker compose up --build
```

Possible services:

```text
nginx
api
ui
simulator
```

Images must be reproducible.

---

## 20. Tests

Every relevant new feature must include tests.

Priority:

1. rover logic;
2. safety rules;
3. API;
4. simulator;
5. configuration;
6. telemetry;
7. AI logic that can be tested without hardware.

Critical cases that must exist:

```text
STOP always works
invalid command is rejected
out-of-range speed is limited or rejected
rover timeout does not block the API
Wi-Fi loss changes rover state to disconnected
reconnection does not block the API
motion command does not remain active indefinitely after link loss
simulator behaves like the expected rover
camera failure does not block manual control
```

---

## 21. Simulator

The simulator is a first-class part of the project, not a temporary element.

It must be able to simulate:

- motion;
- status;
- battery;
- latency;
- timeouts;
- errors;
- communication loss.

Ideally also:

- gradual battery drain;
- virtual position;
- orientation;
- virtual obstacles;
- simulated live camera stream.

This will allow AI to develop and test new features without physical risk.

---

## 22. Documentation

Maintain at least:

```text
README.md
AGENTS.md
diagrams/
```

The README must explain:

- what RoverCarBeto is;
- required hardware;
- architecture;
- installation;
- execution;
- simulator;
- running on Raspberry Pi;
- API;
- tests.

Diagrams must be updated when the architecture changes significantly.

---

## 24. Rules for AI agents

### ALWAYS

- Read this `AGENTS.md` before modifying the project.
- Review related code before writing new code.
- Reuse existing functionality when reasonable.
- Maintain simulator compatibility.
- Write code that humans can understand.
- Add tests for new logic.
- Validate external inputs.
- Handle network errors.
- Use timeouts in communications.
- Keep AI, hardware, and API separated.
- Prioritize safe rover shutdown.
- Explain relevant assumptions.
- Keep documentation synchronized.

### NEVER
- Record or persist camera video.
- Save camera images or snapshots unless explicitly requested in a future project requirement.

- Invent a hardware API without verifying it.
- Delete tests to make a task "pass".
- Disable safety validations.
- Include secrets.
- Execute physical movements during automated tests.
- Couple HTTP endpoints directly to low-level motor calls when a service layer exists.
- Add dependencies without a clear reason.
- Rewrite entire files when a small change is enough.
- Hide exceptions with `except Exception: pass`.
- Claim something works if it has not been validated.
- Allow an AI model to control motors directly without a safety layer.

---

## 25. Decisions under uncertainty

If information is missing about an API, protocol, or hardware component:

1. Do not invent behavior.
2. First search existing project documentation.
3. Consult official Waveshare documentation when available.
4. Verify the actual WAVE ROVER communication protocol before implementing commands.
5. Encapsulate uncertain parts behind interfaces.
6. Implement the simulator first if it allows progress.
7. Clearly mark any temporary assumption.

---

## 26. Project priorities

Recommended development order:

### Phase 1 — Foundation

- repository;
- configuration;
- Docker;
- minimal API;
- health check;
- tests;

### Phase 2 — Simulated rover

- Rover interface;
- motion commands;
- STOP;
- telemetry;
- battery;
- latency;
- simulated failures.

### Phase 3 — Web interface

- simulated video;
- joystick or controls;
- telemetry;
- connection status;
- stop control (visible and redundant; a dedicated STOP button was removed by user
  decision — see `MEMORY.md`).

### Phase 4 — Real hardware

- connection to WAVE ROVER;
- real driver;
- manual control;
- error recovery.

### Phase 5 — Camera

- real-time video;
- simulated camera;
- WebRTC streaming;
- real-time AI inference;
- no image recording;
- no video recording.

### Phase 6 — AI

- detection;
- inference metrics;
- detection visualization;
- tracking.

### Phase 7 — Intelligent behavior

- assisted following;
- obstacle detection;
- semi-autonomous actions.

### Phase 8 — Autonomy

Only when the previous layers are stable:

- navigation;
- planning;
- maps;
- missions;
- safe return.

---

## 27. Definition of done

A task is not considered complete merely because the code compiles.

When applicable, the following must be satisfied:

```text
[ ] Implementation completed
[ ] Code formatted
[ ] Lint passes
[ ] Existing tests still pass
[ ] New tests added
[ ] Works with simulator
[ ] Errors handled
[ ] Contains no secrets
[ ] Documentation updated
[ ] Does not reduce rover safety
```

---

## 28. Project philosophy

RoverCarBeto should evolve through small iterations.

Prefer:

```text
simple
testable
observable
simulatable
safe
modular
documented
```

rather than:

```text
complex
magical
monolithic
hard to test
hardware-dependent
```

AI is a tool to accelerate development, not an excuse to lose control over the architecture.

**Every change should leave RoverCarBeto easier to understand, test, and evolve than before.**
