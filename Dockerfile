FROM python:3.11-slim

WORKDIR /app

# 依赖单一事实源: backend/requirements.txt (2026-07-12 收敛)。
# 不再在 Dockerfile 里手工维护一份残缺依赖列表。
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source code
COPY backend/app ./backend/app

# Copy pre-built frontend (run `npm run build` locally first if needed)
COPY frontend/dist ./frontend/dist
COPY frontend/index.html ./frontend/index.html

ENV PYTHONUNBUFFERED=1
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8000

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
