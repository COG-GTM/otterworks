FROM node:20-alpine AS builder

ARG VITE_COLLAB_WS_URL=ws://localhost:8084
ENV VITE_COLLAB_WS_URL=$VITE_COLLAB_WS_URL

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.inc.template /etc/nginx/templates/security-headers.inc.template

EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

# API_GATEWAY_URL default for runtime (can be overridden by Helm/docker-compose env);
# substituted into the nginx config template at container start.
ENV API_GATEWAY_URL=http://api-gateway:8080

# Extra Content-Security-Policy sources (space-separated), substituted into
# nginx/security-headers.inc.template at container start. file-service presigns
# path-style S3 URLs (https://s3.<region>.amazonaws.com/<bucket>/<key>), and that
# host is shared by every bucket, so storage sources are scoped to the bucket
# path: a bare host or *.amazonaws.com would let injected script send tokens to
# any attacker-owned bucket.
ENV CSP_STORAGE_ORIGINS="https://s3.us-east-1.amazonaws.com/otterworks-files-dev/ https://s3.amazonaws.com/otterworks-files-dev/"
ENV CSP_COLLAB_ORIGINS="ws://localhost:8084 ws://localhost:8085 wss://localhost:8085"
