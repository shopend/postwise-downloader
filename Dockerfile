FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-graphify.txt ./
ARG INSTALL_GRAPHIFY=0
RUN if [ "$INSTALL_GRAPHIFY" = "1" ]; then pip install --no-cache-dir -r requirements-graphify.txt; else pip install --no-cache-dir -r requirements.txt; fi
COPY server.py knowledge_graph.py local_ai.py .
RUN useradd --create-home appuser
USER appuser
EXPOSE 8080
CMD ["python", "server.py"]
