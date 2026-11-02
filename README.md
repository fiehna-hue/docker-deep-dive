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

## Roadmap

- [x] M0 Naive baseline
- [x] M1 Size and cache optimization
- [x] M2 Hardening and scanning
- [ ] M3 Docker Compose: API, Redis, Postgres and nginx with separate networks
- [ ] M4 Break-and-fix lab with an incident log
- [ ] M5 CI pipeline with build cache, scan and push
