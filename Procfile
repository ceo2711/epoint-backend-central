web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: celery -A app.workers.celery_app worker --loglevel=info
release: alembic upgrade head
