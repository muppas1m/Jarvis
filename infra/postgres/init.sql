-- init.sql — runs once on first container start (as POSTGRES_USER = jarvis_admin)
-- Extensions live in the public schema; pg_trgm is a text-search fallback used by
-- the dashboard's freeform search; uuid-ossp gives us gen_random_uuid() compat.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Application user used by the FastAPI/Alembic connection (DATABASE_URL).
CREATE USER jarvis_app WITH PASSWORD 'jarvis_dev_password';
GRANT ALL PRIVILEGES ON DATABASE jarvis TO jarvis_app;

-- Postgres 15+ revoked CREATE on the public schema for non-owners.
-- Without these grants, Alembic (which connects as jarvis_app) cannot create
-- tables in the default schema and the migration in Turn 4 fails.
GRANT USAGE, CREATE ON SCHEMA public TO jarvis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON TABLES TO jarvis_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON SEQUENCES TO jarvis_app;
