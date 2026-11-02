# docker-deep-dive

A small Flask API used to learn Docker properly: measure a naive image, then fix it step by step and prove every improvement with numbers.

## Results (measured on Docker Desktop for Mac)

| | Naive (Dockerfile.naive) | Optimized and hardened (Dockerfile) |
|---|---|---|
| Image size on disk | 1.63 GB | 187MB |
| Rebuild after a one-line code change | 11.8 s (pip reinstalls) | 1.8 s (all layers cached) |
| Runs as | root | appuser (uid 10001) |
| Trivy HIGH + CRITICAL findings | 471 (455 HIGH, 16 CRITICAL) | 45 (45 HIGH, 0 CRITICAL) |

Trivy numbers are a snapshot from 2026-11-02 and change as base images are updated. Most of the remaining findings are in the Debian base image.

## What changed and why

- Slim base image: python:3.12-slim instead of the full python:3.12 image, which carries compilers and tools the app never uses.
- Multi-stage build: dependencies are installed in a throwaway stage, and only the result is copied into the runtime image.
- Layer order: requirements.txt is copied and installed before the app code, so a code change does not reinstall dependencies.
- .dockerignore keeps git history, caches and secrets out of the build context.
- Production server: gunicorn instead of the Flask development server.
- Non-root user and a HEALTHCHECK baked into the image.

## Runtime hardening, tested

Run command: docker run -d --name v2 -p 8000:8000 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true --memory 128m --pids-limit 100 ddd:v2

- whoami prints appuser, not root.
- Writing to the app directory fails with: Read-only file system.
- CapEff is 0000000000000000, meaning zero Linux capabilities.
- The container reports healthy; memory use was 56 MiB of the 128 MiB limit.

## Reproduce

Build the naive image: docker build -f Dockerfile.naive -t ddd:naive .
Build the optimized image: docker build -t ddd:v2 .
Scan an image: docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --severity HIGH,CRITICAL --quiet ddd:v2

## M3: four-service stack with network isolation

    host :8080 -> nginx -> api (scalable) -> redis
                                         -> db (Postgres, named volume)

    frontend network: nginx, api
    backend network (internal, no internet access): api, redis, db

Tested:
- Only nginx publishes a port. api, redis and db are not reachable from the host.
- nslookup db and nslookup redis from inside the nginx container fail with NXDOMAIN; only api resolves.
- The database password is a Docker secret read from a file (never an environment variable, never committed).
- Data survives docker compose down and up through a named volume.
- The API runs read-only, with all capabilities dropped, no-new-privileges, and memory and process limits.
- The API was scaled from 2 to 3 to 1 replicas while nginx kept running (see docs/incident-log.md for the nginx lesson).

Run it: mkdir -p secrets, then openssl rand -hex 16 > secrets/db_password.txt, then docker compose up -d --build --scale api=2, then curl localhost:8080/health

Known limits: nginx itself runs as the default image user, and Redis has no password because it is only reachable on the internal network.

## Roadmap

- [x] M0 Naive baseline
- [x] M1 Size and cache optimization
- [x] M2 Hardening and scanning
- [x] M3 Docker Compose: API, Redis, Postgres and nginx with separate networks
- [x] M4 Break-and-fix lab (3 deliberate failures, incidents 2-4 in docs/incident-log.md)
- [x] M5 CI pipeline: smoke test, build cache, Trivy scan, push to GHCR

## Break-and-fix lab (M4)

Each override file breaks the stack in one specific way. The diagnosis and fix for each is written up in [docs/incident-log.md](docs/incident-log.md).

| Override file | What it breaks | Symptom | Key evidence |
|---|---|---|---|
| compose.break-oom.yaml | Memory limit of 20 MB on the api | exit 137, nginx never starts | `docker inspect` shows OOMKilled=true |
| compose.break-secret.yaml | Typo in the secret file path | exit 3, worker failed to boot | Traceback names the missing file |
| compose.break-network.yaml | api removed from the backend network | exit 1 after about 24 s of retries | DNS test: `db` resolves on backend, not on frontend |

Reproduce any of them, then restore with a plain `docker compose up -d`:

    docker compose -f compose.yaml -f compose.break-oom.yaml up -d
    docker compose up -d

## CI pipeline (M5)

![ci](https://github.com/fiehna-hue/docker-deep-dive/actions/workflows/ci.yml/badge.svg)

Every push and pull request runs [.github/workflows/ci.yml](.github/workflows/ci.yml):

1. **Smoke test:** builds and starts the full four-service stack, waits for every healthcheck, then calls /health and creates and lists an item through nginx.
2. **Cached build:** BuildKit layer cache stored in GitHub Actions, so unchanged layers are not rebuilt.
3. **Trivy scan:** the pipeline fails on any fixable CRITICAL vulnerability.
4. **Publish:** only on `main`, the image is pushed to GitHub Container Registry tagged `latest` and with the commit SHA.

Pull the published image:

    docker pull ghcr.io/fiehna-hue/docker-deep-dive:latest
