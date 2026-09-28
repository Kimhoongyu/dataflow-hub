import os

from sqlalchemy import URL, create_engine

# URL.create safely handles passwords containing URL-reserved characters.
database_url = URL.create(
    "postgresql+psycopg",
    username=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    host=os.getenv("POSTGRES_HOST", "db"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    database=os.environ["POSTGRES_DB"],
)
engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=3,
    connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
)
