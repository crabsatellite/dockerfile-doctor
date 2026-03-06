# Security anti-patterns Dockerfile
MAINTAINER john@example.com

FROM ubuntu:22.04

# Secrets in ENV — never do this
ENV DB_PASSWORD=supersecret123
ENV API_KEY=sk-live-abcdef1234567890
ENV AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
ENV MYSQL_ROOT_PASSWORD=rootpass
ENV SECRET_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

RUN apt-get update && apt-get install -y \
    curl \
    wget \
    openssh-server \
    && rm -rf /var/lib/apt/lists/*

# Expose insecure ports
EXPOSE 23
EXPOSE 21
EXPOSE 3389

COPY . /app
WORKDIR /app

# No USER instruction — running as root
CMD ["python", "app.py"]
