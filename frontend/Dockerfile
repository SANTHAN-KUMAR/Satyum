# Satyum frontend — build the React app, serve it (and reverse-proxy /api + /ws) with nginx.
# Build context is the REPO ROOT:  docker build -f frontend/Dockerfile -t satyum-frontend .

# --- build stage ---
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# No VITE_API_BASE_URL: the app calls relative /api and /ws, which nginx proxies same-origin.
RUN npm run build          # -> /app/dist

# --- serve stage ---
FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
