# Logstead Backend

This is the FastAPI backend for Logstead.
## Structure
- All backend code is in the `app/` subfolder (i.e., `backend/app/`).
- The outer `backend/` contains Poetry files, Dockerfile, and test config.

## Getting Started

1. Install Poetry (if not already):
   ```bash
   pip install poetry
   ```
2. Ensure Poetry uses in-project virtualenvs (recommended, one-time):
   ```bash
   poetry config virtualenvs.in-project true
   ```
3. Install dependencies (from the outer backend directory):
   ```bash
   poetry install
   ```
4. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```
5. Run the server:
   ```bash
   poetry run uvicorn app.main:app --reload
   ```

The API will be available at http://localhost:8000

## Docker
- The backend Dockerfile expects this structure and runs the app as a package.
- Use Docker Compose from the project root for local orchestration.
