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
