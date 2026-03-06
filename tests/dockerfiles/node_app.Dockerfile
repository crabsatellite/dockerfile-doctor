# Typical Node.js app with common mistakes
FROM node:latest

MAINTAINER developer@company.com

WORKDIR /app

# COPY everything first — bad for cache (DD011)
COPY . .

# npm install instead of npm ci (DD016)
RUN npm install

# Multiple separate RUN instructions (DD005)
RUN npm run build
RUN npm prune --production

# ADD for local file instead of COPY (DD008)
ADD config.json /app/config.json

ENV SESSION_SECRET=keyboard-cat-secret

# No USER instruction (DD006)
# No HEALTHCHECK (DD010)

EXPOSE 3000

# Shell form CMD (DD012)
CMD npm start
