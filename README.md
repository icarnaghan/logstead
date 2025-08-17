# Logstead

Logstead is a property and equipment tracking application for homeowners and property investors. It helps manage maintenance, repairs, and service records for multiple properties.

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
```
cd frontend
npm install
npm run dev
```
App will be available at http://localhost:5173 (default Vite port).

#### Build for production:
```
cd frontend
npm run build
```
Output will be in `frontend/dist`.

#### Preview production build locally:
```
cd frontend
npm run preview
```
App will be available at http://localhost:4173.

#### Lint:
```
cd frontend
npm run lint
```

## Project Structure
- `frontend/` - React app
- `backend/` - FastAPI app (Python, Poetry)
- `infrastructure/` - IaC (Terraform/Pulumi)
- `observability/` - Monitoring/logging configs
- `k8s/` - Kubernetes manifests
- `.github/` - Copilot instructions

## Getting Started
1. Clone the repo
2. See `README.md` in each subfolder for service-specific instructions
3. Use Docker Compose for local dev:
	```
	docker compose up --build
	```
	- Frontend: http://localhost:3000
	- Backend: http://localhost:8000
	- Keycloak: http://localhost:8080
	- RabbitMQ: http://localhost:15672

## License
[MIT](LICENSE)
