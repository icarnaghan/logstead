# Logstead Backend

This is the FastAPI backend for Logstead.

## Structure
- All backend code is now in the `app/` subfolder (i.e., `backend/app/`).
- The outer `backend/` contains Poetry files, Dockerfile, and test config.

## Getting Started

1. Install Poetry:
   ```bash
   pip install poetry
   ```
2. Install dependencies:
   ```bash
   poetry install
   ```
3. Run the server (from the outer backend directory):
   ```bash
   poetry run uvicorn backend.main:app --reload
   ```

The API will be available at http://localhost:8000

## Docker
- The backend Dockerfile expects this structure and runs the app as a package.
- Use Docker Compose from the project root for local orchestration.
