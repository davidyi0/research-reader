# Production build only — local dev still uses the Vite dev server directly,
# per docker-compose.yml's frontend service.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite env vars are compiled into the bundle at build time, not read at
# container start, so these must be build args, not runtime env vars.
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_API_URL=""
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
