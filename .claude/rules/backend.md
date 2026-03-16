---
paths:
  - "backend/**/*.py"
---

# Backend Rules
- Use async/await for all new endpoints
- Validate input with Pydantic schemas
- All DB operations through SQLAlchemy async session
- Migrations via Alembic — never modify DB schema directly
- Tests in backend/tests/ mirroring the app/ structure
