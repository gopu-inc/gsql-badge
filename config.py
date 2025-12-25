import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://volve_user:odM5spc4DLMdEPJww834aDNE7c49J9bG@dpg-d4vpeu24d50c7385s840-a.oregon-postgres.render.com/volve?sslmode=require"
)
