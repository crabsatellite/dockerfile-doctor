# syntax=docker/dockerfile:1

# ---- Build stage ----
FROM node:20.11.1-alpine3.19 AS builder

WORKDIR /app

# Copy dependency files first for cache optimization
COPY package.json package-lock.json ./
RUN npm ci --production=false

# Copy source code
COPY tsconfig.json ./
COPY src/ src/
RUN npm run build && \
    npm prune --production

# ---- Production stage ----
FROM node:20.11.1-alpine3.19

LABEL maintainer="team@example.com" \
      version="1.0.0" \
      description="Production Node.js application"

WORKDIR /app

# Install tini for proper signal handling
RUN apk add --no-cache tini

# Copy built artifacts from builder
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./

# Use non-root user
RUN addgroup -g 1001 appgroup && \
    adduser -u 1001 -G appgroup -D appuser
USER appuser:appgroup

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "--quiet", "--tries=1", "--spider", "http://localhost:3000/health"]

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/server.js"]
