FROM python:3.11-slim

WORKDIR /app

# Install only essential packages
RUN pip install --no-cache-dir \
    fastapi==0.115.9 \
    uvicorn==0.30.6 \
    python-dotenv==1.0.1 \
    pydantic==2.10.6 \
    pydantic-settings==2.7.1 \
    openai==2.36.0 \
    httpx==0.28.1 \
    python-multipart==0.0.6 \
    sse-starlette==2.1.3

# Copy backend source code
COPY backend/app ./backend/app
COPY backend/requirements.txt ./

# Copy pre-built frontend (run `npm run build` locally first if needed)
COPY frontend/dist ./frontend/dist
COPY frontend/index.html ./frontend/index.html

ENV PYTHONUNBUFFERED=1
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8000

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]