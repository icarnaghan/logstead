# Logstead

Logstead is a property and equipment tracking application for homeowners and property investors. It helps manage maintenance, repairs, and service records for multiple properties.

## Monorepo Structure
- `frontend/` — React 19 + Vite app
- `backend/` — FastAPI backend (all code in `backend/app/`, Poetry-managed venv in `backend/.venv`)
- `docker-compose.yml` — Orchestrates all services from the project root

## Features
- Property portfolio dashboard
- Equipment/appliance tracking (age, model, warranty, service history)
- Maintenance log and reminders
- Document upload (receipts, manuals, warranties)
- Smart notifications for recurring maintenance
- API integrations (e.g., Zillow)
- Keycloak authentication (planned)
- AI features (LangChain, planned)
- Queueing system (RabbitMQ/Kafka, planned)
- Observability stack (Prometheus, Grafana, Loki)

## Tech Stack
- Frontend: React 19 (with Vite, TypeScript)
- Backend: FastAPI (Python, Poetry)
- Auth: Keycloak
- CI/CD: GitLab CI
- Containerization: Docker, Kubernetes (K3s/EKS)
- Infrastructure as Code: Terraform/Pulumi

## Local Development
- Use Docker Compose or K3s for local orchestration
- See `docker-compose.yml` for service definitions

### Frontend (React 19 + Vite)

#### Run locally (development, hot reload):
```bash
cd frontend
npm install
npm run dev
```
App will be available at http://localhost:5173 (default Vite port).

### Backend (FastAPI)

#### Run locally (development, hot reload):
```bash
cd backend
poetry config virtualenvs.in-project true  # recommended, one-time
poetry install
source .venv/bin/activate
poetry run uvicorn app.main:app --reload
```
App will be available at http://localhost:8000

#### Build and run with Docker Compose:
```bash
docker compose up --build
```

---

For more details, see the `backend/README.md` and `frontend/README.md`.

## License
[MIT](LICENSE)
