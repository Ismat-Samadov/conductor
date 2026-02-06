import os
from dotenv import load_dotenv

load_dotenv()

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# LLM
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash")

# App
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEFAULT_SEARCH_RADIUS_METERS = int(os.getenv("DEFAULT_SEARCH_RADIUS_METERS", "500"))
TRANSFER_MAX_DISTANCE_METERS = int(os.getenv("TRANSFER_MAX_DISTANCE_METERS", "300"))
MAX_TRANSFER_COUNT = int(os.getenv("MAX_TRANSFER_COUNT", "2"))
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "az")
