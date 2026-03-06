# Multi-stage build — mostly good, a few issues
FROM golang:1.22-alpine AS builder

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /app/server ./cmd/server

# --- Production stage ---
FROM alpine:3.19

LABEL maintainer="devteam@example.com"

WORKDIR /app

# Missing --no-cache on apk (minor, not a rule)
RUN apk add --no-cache ca-certificates tzdata

COPY --from=builder /app/server .

USER nobody:nobody

EXPOSE 8080

# Shell form CMD — triggers DD012
CMD ./server --port=8080
