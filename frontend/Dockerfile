# Vite + React 19 production Dockerfile
FROM node:24-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.25-alpine AS serve
WORKDIR /usr/share/nginx/html
RUN apk update && apk upgrade --no-cache
COPY --from=build /app/dist .
COPY --from=build /app/public ./public
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
