from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Welcome to Logstead API"}


# Sample API endpoint for frontend testing
@app.get("/api/hello")
def hello():
    return {"greeting": "Hello from FastAPI!"}
