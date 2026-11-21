"""
Database layer: SQLAlchemy models, engine/session setup, value helpers and Alembic migrations.

Owner: DB team.
- database.py   engine + session factory from DATABASE_URL (relative SQLite paths resolved, foreign keys on)
- models.py     the schema; import it as a module (`from app.db import models`)
- types.py      money <-> cents, exact decimal <-> TEXT, UTC timestamps
- migrations/   Alembic environment and versions; apply with `cd backend && alembic upgrade head`

Importing this package never connects to or creates a database.
"""
