from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Silvera API",
    description="Secure Enterprise Intelligence",
    version="0.1.0",
)

# Development configuration: allow the local Vite frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Welcome to Silvera"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/api/status")
def api_status():
    return {
        "name": "Silvera",
        "status": "online",
        "message": "Backend connection successful",
    }
