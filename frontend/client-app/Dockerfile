FROM node:20-alpine AS builder

ARG VITE_COLLAB_WS_URL=ws://localhost:8084
ENV VITE_COLLAB_WS_URL=$VITE_COLLAB_WS_URL

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

# nginx 1.30.7 (stable): first stable release with the NGINX2Root HTTP/2 fixes.
# nginxinc/nginx-unprivileged has no 1.30.7+ build yet, so start from the
# official image (exact version + digest) and apply the same unprivileged
# changes: no `user` directive, pid and temp paths under /tmp, uid 101.
# scripts/check-nginx-version.sh enforces the floor in CI.
FROM nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3
RUN sed -i '/^user  nginx;/d' /etc/nginx/nginx.conf \
 && sed -i 's,^pid .*;,pid        /tmp/nginx.pid;,' /etc/nginx/nginx.conf \
 && sed -i '/^http {/a \    proxy_temp_path /tmp/proxy_temp;\n    client_body_temp_path /tmp/client_temp;\n    fastcgi_temp_path /tmp/fastcgi_temp;\n    uwsgi_temp_path /tmp/uwsgi_temp;\n    scgi_temp_path /tmp/scgi_temp;' /etc/nginx/nginx.conf \
 && rm -f /etc/nginx/conf.d/default.conf \
 && chown -R 101:0 /var/cache/nginx /etc/nginx \
 && chmod -R g+w /var/cache/nginx /etc/nginx
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

USER 101

EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

# API_GATEWAY_URL default for runtime (can be overridden by Helm/docker-compose env);
# substituted into the nginx config template at container start.
ENV API_GATEWAY_URL=http://api-gateway:8080
