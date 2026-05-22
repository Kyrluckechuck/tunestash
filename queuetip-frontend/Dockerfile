FROM node:20-alpine AS node-base
WORKDIR /app
RUN apk add --no-cache yarn

FROM node-base AS deps
COPY package.json yarn.lock* ./
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn,id=yarn-cache-queuetip,sharing=locked \
    yarn install --frozen-lockfile

FROM deps AS source
COPY . .

FROM source AS development

EXPOSE 3001
CMD ["yarn", "dev", "--host", "0.0.0.0", "--port", "3001"]

FROM source AS build
RUN yarn build

FROM nginx:alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
# Single-origin nginx config: serves the static build + proxies /graphql,
# /auth/, /exports/ to the queuetip backend container. Mirrors TuneStash's
# frontend/nginx.conf so the browser never sees a cross-origin request.
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN apk add --no-cache wget
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

FROM production
