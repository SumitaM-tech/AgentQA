# Stage 1: build the static bundle. VITE_API_URL is baked in at build time (it is public; never put secrets here).
FROM node:20-alpine AS build
WORKDIR /app
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
COPY package*.json ./
RUN npm ci --legacy-peer-deps
COPY . .
RUN npm run build

# Stage 2: serve with nginx (SPA fallback, gzip, security headers, long-cache for hashed assets).
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/healthz >/dev/null || exit 1
