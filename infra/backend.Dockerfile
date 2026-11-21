FROM python:3.11-slim
WORKDIR /workspace
COPY backend/requirements.lock backend/requirements.lock
RUN pip install --no-cache-dir -r backend/requirements.lock
COPY backend backend
COPY scripts scripts
COPY data data
COPY evaluation/results evaluation/results
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
