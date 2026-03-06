# Performance anti-patterns Dockerfile
FROM ubuntu:latest

WORKDIR /app

# Separate apt-get update and install (DD002)
RUN apt-get update
RUN apt-get install -y python3 python3-pip curl wget git

# Missing --no-install-recommends (DD003)
# Missing apt cache cleanup (DD004)
# Multiple consecutive RUN instructions (DD005)
RUN pip3 install --upgrade pip
RUN pip3 install flask
RUN pip3 install requests
RUN pip3 install gunicorn

# COPY . . before dependency install (DD011)
COPY . .
RUN pip3 install -r requirements.txt

# npm install instead of npm ci (DD016)
RUN npm install

# Large base image used (DD017) — ubuntu instead of slim/alpine

EXPOSE 5000
CMD ["python3", "app.py"]
