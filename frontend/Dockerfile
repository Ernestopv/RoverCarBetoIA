# RoverCarBeto frontend image.
# Build context is the repository root so this file can also copy docker/nginx.conf.
#
#   docker build -f frontend/Dockerfile -t rovercarbeto-ui .

# --- Build stage -------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Dependencies first: cached unless the lockfile changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --- Serve stage -------------------------------------------------------------
FROM nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
