# HeadStart online (Render, or any Docker host). The host may set PORT.
FROM python:3.12-slim

# India time, so "today" and "now" are the user's, not the server's.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Kolkata PYTHONUNBUFFERED=1 \
    HEADSTART_HOSTED=1 HEADSTART_PLANNERS=/app/planners PORT=10000

# Not as root.
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
RUN mkdir -p /app/planners && chown -R user /app
USER user

EXPOSE 10000
CMD ["python", "app.py"]
