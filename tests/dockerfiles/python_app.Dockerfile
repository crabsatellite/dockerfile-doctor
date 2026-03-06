# Typical Python web app with common mistakes
FROM python:3.11

WORKDIR /app

# pip install without --no-cache-dir (DD015)
RUN pip install poetry

# COPY everything before dependency install (DD011)
COPY . .

RUN pip install -r requirements.txt

# apt-get install without recommends or cleanup
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc

# No USER (DD006)
# No HEALTHCHECK (DD010)

EXPOSE 8000

CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8000"]
