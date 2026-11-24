FROM node:22-alpine AS build
WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:alpine

RUN rm -f /etc/nginx/conf.d/default.conf \
    && addgroup -S -g 10001 moviehub \
    && adduser -S -D -H -u 10001 -G moviehub moviehub \
    && mkdir -p /tmp/client_temp /tmp/proxy_temp /tmp/fastcgi_temp /tmp/uwsgi_temp /tmp/scgi_temp \
    && chown -R 10001:10001 /tmp /usr/share/nginx/html

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build --chown=10001:10001 /app/dist /usr/share/nginx/html

USER 10001:10001
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
