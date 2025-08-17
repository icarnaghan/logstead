
from fastapi import FastAPI
from backend.services.property.routes import router as property_router



app = FastAPI()
app.include_router(property_router, prefix="/api")


@app.get("/")
def read_root():
    return {"message": "Welcome to Logstead API"}


# Sample API endpoint for frontend testing
@app.get("/api/hello")
def hello():
    return {"greeting": "Hello from FastAPI!"}
