# Maintainability anti-patterns Dockerfile
FROM python:latest

# Relative WORKDIR (DD013)
WORKDIR app

# apt-get upgrade (DD014)
RUN apt-get update && apt-get upgrade -y

# ADD instead of COPY for local files (DD008)
ADD requirements.txt /app/requirements.txt
ADD . /app

RUN pip install -r requirements.txt

# Shell form CMD (DD012)
CMD python app.py

# No HEALTHCHECK (DD010)
# No USER instruction (DD006)
# latest tag (DD001)
