"""Conductor — Bakı ictimai nəqliyyat Graph RAG API."""

from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from conductor.config import APP_HOST, APP_PORT
from conductor.graph.client import Neo4jClient
from conductor.api.routes import router, init_services

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    client = Neo4jClient()
    client.verify_connectivity()
    init_services(client)
    print("Conductor API ready.")
    yield
    # Shutdown
    client.close()
    print("Neo4j connection closed.")


app = FastAPI(
    title="Conductor",
    description="Bakı ictimai nəqliyyat köməkçisi — Graph RAG API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.head("/")
async def health():
    """Render and other PaaS use HEAD / for health checks."""
    return Response(status_code=200)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("conductor.main:app", host=APP_HOST, port=int(APP_PORT), reload=True)
