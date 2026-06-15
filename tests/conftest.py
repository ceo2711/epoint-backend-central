import os

import pytest

# Variables mínimas antes de importar la app
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars")
os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "true")


@pytest.fixture
def anyio_backend():
    return "asyncio"
