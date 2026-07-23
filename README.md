# TService

TService is a scaffold for building local web services. It provides a consistent project structure, setup and deployment scripts, a local-first API pattern with health endpoint, a browser UI, and optional ServiceHandler integration — ready to be adapted to any new service.

## About

TService binds to `127.0.0.1` on port `49150` and rejects non-local requests. It serves as a starting point: rename, repurpose, and fill in the business logic.

**What's included:**

- **Project structure** — scripts, deployment, resources, src/models, and ui folders following the same conventions as Cipher, DiskIdentifier, YoutubeDownloader, LibraccioAPI, and ServiceHandler.
- **Health endpoint** — `GET /api/health` returns service status, bind address, port, hostname, and PID.
- **Browser UI** — a landing page with project title, description, and an empty card ready to hold service-specific content. Styling and page-entry animations match LibraccioAPI.
- **Local-only access control** — all `/api/*` endpoints are restricted to the local device.
- **Headless mode** — set `"noGUI": true` in configuration to disable UI routes.
- **ServiceHandler integration** — optionally registers with ServiceHandler for service discovery and endpoint registration.

> **Note**: TService is a template. The card in the UI is intentionally empty. Add your own form, data display, or interactive elements by editing `ui/pages/index.html` and `ui/css/index.css`.

## How to use

1. Clone or copy the scaffold.
2. Rename the project (replace "TService" with your service name across all files).
3. Add your API endpoints to `src/main.py`.
4. Add your request/response models to `src/models/` if needed.
5. Update `ui/pages/index.html` and `ui/css/index.css` with your UI.

## Setup

1. Copy `.env.example` to `.env` and adjust any overrides (see below).
2. Install Python dependencies: `pip install -r requirements.txt`.
3. Review `resources/configuration.json` to configure port, UI visibility, and ServiceHandler integration.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TSERVICE_PORT` | `49150` | Override the service port. |

| `TSERVICE_SERVICEHANDLER_DISABLED` | `false` | Set to `true` to prevent registration with ServiceHandler. |

## Run

1. Windows: `scripts\run.bat`
2. Unix-like: `bash scripts/run.sh`
3. Manual: `python src/main.py` from the project root.

## ServiceHandler Integration

TService can register with ServiceHandler for service discovery. Set `servicehandlerEnabled` in `resources/configuration.json`. A background keepalive thread re-registers every 15 seconds if needed.

## Access Control

All `/api/*` endpoints are local-device only. Non-local requests are rejected with `403`.

## License

- [LICENSE](LICENSE)

## Author

- Replace with your name
