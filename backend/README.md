## Code Quality & pre-commit

This project uses [pre-commit](https://pre-commit.com/) for automated code quality checks.

To use pre-commit, you must either:

1. Activate the Poetry virtual environment:
   ```bash
   source .venv/bin/activate
   pre-commit run --all-files
   ```

2. Or run pre-commit directly with Poetry (no need to activate venv):
   ```bash
   poetry run pre-commit run --all-files
   ```

pre-commit is automatically run on every git commit if installed and set up.
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
