# Incident log

## 1. nginx sent every request to one of two API replicas

**Symptom:** With two API replicas running and healthy, six requests in a row were all answered by the same container ID.

**Diagnosis:**
- docker compose ps showed both replicas healthy.
- nslookup api from inside the nginx container returned both addresses (172.20.0.2 and 172.20.0.3).
- Calling each replica directly from the nginx container worked and returned two different container IDs.
- Calling the name api:8000 from the nginx container with wget alternated between the replicas.
- I added a log format with the upstream address. It showed nginx used only one address, and which one changed between nginx restarts (172.20.0.2 once, 172.20.0.3 another time).

**Cause:** The upstream block names the hostname api. nginx resolves that name once, when it starts, and it ended up with a single replica address. A restart simply picks again. I did not investigate why only one of the two addresses was kept.

**Fix:** Removed the upstream block, added the resolver 127.0.0.11 valid=2s ipv6=off line (Docker's embedded DNS, re-resolved every 2 seconds), and passed the backend to proxy_pass through a variable so nginx resolves it at request time.

**Verification:**
- Requests are now spread across both replicas in the upstream log.
- Scaling the API from 2 to 3 replicas without restarting nginx: a third address (172.20.0.5) appeared in the log.
- Scaling down to 1 replica: 10 of 10 requests returned 200. A short burst of 502 errors is still possible while the 2-second DNS cache expires, but it was not observed.

**Lessons:**
- Log the upstream address ($upstream_addr). It turned a guess into a fact in one step.
- Restarting a service is not a diagnosis; it can hide or randomize the problem.
- Test one layer at a time (DNS, each replica directly, then the proxy) to find which layer is wrong.

## Incident 2: API container killed instantly (exit 137, OOMKilled)

**Symptom:** `docker compose up` failed with "dependency failed to start: container docker-deep-dive-api-1 exited (137)". nginx stayed in the Created state and the site never came up.

**Diagnosis:**
- `docker compose ps -a` showed api Exited (137) while db and redis were healthy, and nginx was never started because it depends on api being healthy.
- `docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}'` returned `true 137`. Exit code 137 is 128 + 9, meaning SIGKILL.
- `docker compose logs api` stopped right after "Booting worker" with no Python traceback. An OOM kill is a SIGKILL from the kernel, so the app gets no chance to log anything.

**Cause:** A memory limit of 20 MB was applied to the api container (via an override file). Two gunicorn workers plus Flask need more than that, so the kernel killed the container within seconds of start.

**Fix:** Removed the override so the api runs with its intended 128 MB limit. The stack reached healthy and /health returned ok.

**Lessons:**
- Exit 137 plus OOMKilled=true means memory limit, not an application bug. Check inspect before reading code.
- A log that stops abruptly with no error is itself a clue.
- Set limits from measurement (docker stats) with headroom, not by guessing.
- depends_on with service_healthy turns one failure into a clear chain: api fails, so nginx never starts.

## Incident 3: API fails to boot, secret file not found (exit 3)

**Symptom:** `docker compose up` failed with "dependency failed to start: container docker-deep-dive-api-1 exited (3)". The api never became healthy.

**Diagnosis:**
- `docker compose ps -a` showed api Exited (3) while db and redis were healthy.
- `docker compose logs api` contained a full Python traceback ending in `FileNotFoundError: No such file or directory: '/run/secrets/db_passwrd'`. The call chain was init_db, then connect, then read_secret, then open(path).
- Followed by gunicorn's "Worker failed to boot", which explains exit code 3. Gunicorn uses 3 when workers cannot start.
- `ls /run/secrets` in the db container showed the real file is named `db_password`, so the path in DB_PASSWORD_FILE had a typo.

**Cause:** DB_PASSWORD_FILE pointed at /run/secrets/db_passwrd, a file that does not exist. Because the app reads its secret at import time, the failure happened at startup rather than on the first request.

**Fix:** Corrected the path to /run/secrets/db_password (by removing the override). The api became healthy and /health returned ok.

**Lessons:**
- Read the last line of the traceback first: the error names the exact bad path.
- Failing fast at startup is good. A bad config is caught immediately instead of at 3 a.m. on the first user request.
- Gunicorn exit code 3 means a worker failed to boot, so the real error is always in the logs above it.
- Secrets mounted at /run/secrets/<name> must match the name in the compose `secrets:` section exactly.

## Incident 4: API cannot reach the database (network isolation)

**Symptom:** `docker compose up` took about 24 seconds, then failed with "dependency failed to start: container docker-deep-dive-api-1 exited (1)". db and redis were healthy.

**Diagnosis:**
- The slow failure is a clue. Wrong passwords and missing files fail instantly (incidents 1 and 3). Taking about 24 seconds matches the retry loop in init_db() trying to reach the database until it gives up.
- Grepping the api logs for connection errors returned nothing, because the retry loop swallows the exception. The cause was not visible in the logs.
- Tested name resolution from a throwaway container using the same image:
  - on the frontend network, `gethostbyname('db')` raised `socket.gaierror: Name or service not known`
  - on the backend network, it resolved to 172.19.0.3
- The api had been attached to the frontend network only. The database lives on the internal backend network, so the name never resolved.

**Cause:** The api service was removed from the backend network, so Docker's embedded DNS could not resolve `db` for it.

**Fix:** Restored the api to both networks (frontend and backend) by removing the override. The api became healthy and /health returned ok.

**Lessons:**
- Slow failure points to retries and unreachable hosts. Instant failure points to bad config.
- Testing name resolution from a throwaway container on each network separates a network problem from a password or database problem.
- Observability gap found: the app hides the last connection error. Follow-up: log the exception on each retry so the cause is visible in `docker compose logs`.
- Putting the database on an internal-only network is a security feature. It also means every service that needs it must be attached explicitly.
