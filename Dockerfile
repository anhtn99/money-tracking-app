FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runs as a non-root user -- this container is reachable from the public
# internet in both AWS environments (Phase 7), so staying root the whole
# time is an avoidable risk for no benefit (nothing here needs root: no
# privileged ports, no system package installs at runtime).
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
