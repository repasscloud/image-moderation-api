# Swoovr image moderation — Alpine installer

One installer for every VM. Run it, choose what the machine is, answer that role's questions.

```text
Client ──HTTPS :443──▶ caddy-01 (public IP: Caddy + UFW)
                           │  HTTP over the VPC, round-robin
              ┌────────────┼────────────┐
        img-app-01:8080  img-app-02:8080  …     (VPC IP only)
        processor+ClamAV processor+ClamAV
```

## 1. Build and copy the bundle

From a checkout of this repo:

```sh
sh deploy/alpine/bundle.sh                       # -> ./swoovr-alpine.tar.gz
scp swoovr-alpine.tar.gz root@VM:/root/
ssh root@VM
tar xzf swoovr-alpine.tar.gz && cd swoovr-alpine
./install.sh                                     # or: ./install.sh image-moderation | caddy
```

The bundle includes the processor stack files from `deploy/vultr` (`compose.yaml`, `stack.sh`,
`validate.py`, and `compose.env.example`, which supplies the digest-pinned image). If you copy
`deploy/alpine` on its own, the processor installer clones the public repo instead.

## 2. Order of operations

1. Create one Vultr VPC. Create all VMs (Alpine) in the same region and attach each to the VPC.
   Use `ip -4 addr` on each VM to confirm it has a VPC IPv4. Don't assume the interface is `eth1`.
2. **Processors first.** Run `./install.sh image-moderation` on each processor.
3. **Gateway.** Run `./install.sh caddy` on `caddy-01`.
4. Point the domain's DNS **A** record at `caddy-01`'s public IPv4 and remove stale A/AAAA records.
   Caddy gets the TLS certificate automatically. If you use Cloudflare, start with DNS-only.
5. On the gateway, run `swoovr-gateway-test`.

## image-moderation

The installer asks for:

| Prompt | Notes |
| --- | --- |
| VPC IPv4 to bind | Defaults to this VM's first private IPv4. Must be private and assigned to this VM. Port 8080 is published on this address only. |
| Caddy gateway VPC IPv4 | Only this IP may reach :8080. Leave it blank to allow the whole VPC subnet. |
| `API_KEY` | Hidden, at least 32 characters. **Use the same key on every processor.** |
| `ARACHNID_API_USERNAME` / `ARACHNID_API_PASSWORD` | The password is hidden. |

It then runs `image-moderation/steps/01–07`: packages, Docker on nftables with the UFW defaults
(deny incoming/routed, SSH 22 open), stack files, `compose.env` with validation, Docker
networks with the matching UFW route rules, start (`/ready` must return 200), and the 03:00
ClamAV refresh cron. It **reboots only if every step succeeds**. If a step fails, fix the cause
and rerun that step (`sh image-moderation/steps/NN-*.sh`) or the whole installer.

Files go in `/opt/swoovr-image`. `private/` (mode 0700) holds `processor.env` (secrets),
`compose.env` and `install.conf`. `stack/` holds the Compose files. The `control/` directory
receives the drain file.

```sh
sh /opt/swoovr-image/stack/stack.sh /opt/swoovr-image/private/compose.env status|drain|resume|stop
docker logs --tail 100 swoovr-image-processor-1
/usr/local/bin/update-clamav.sh          # run the daily ClamAV refresh by hand
```

**Never** run `docker compose down -v` and never prune volumes. The ClamAV database and the
model cache live in volumes.

## caddy

The installer asks for the **domain** and the **processor VPC IPs**, one per line; any number
is allowed. It checks that it has a route to each IP. It installs `caddy` and `ufw` (public TCP
80/443, SSH 22), writes the pool to `/etc/swoovr-caddy/backends`, generates
`/etc/caddy/Caddyfile`, and starts Caddy.

What the generated config does:

- Only `POST /v1/process` is proxied. Every other path, including `/ready`, `/health` and
  `/docs`, returns 404.
- Requests go round-robin to all backends. Caddy probes `GET /ready` every 10s, so a backend
  returning 503 (draining or stale signatures) drops out of rotation after 2 failures and comes
  back after 2 passes.
- **All request headers are forwarded unchanged**, including `Authorization`, and the original
  `Host` is kept. Caddy adds `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host`.
- POSTs are never retried on another backend, so jobs are not replayed. The upstream
  response-header timeout is 180s, and the upload limit is 12 MB.
- `grace_period 200s`: when the pool changes, requests already in flight finish on the old
  config.

### Managing the pool

```sh
swoovr-backend list                    # members + /ready status
swoovr-backend add 10.1.96.7           # adds only if its /ready returns 200 (--force to skip)
swoovr-backend remove 10.1.96.5        # refuses to remove the last backend
swoovr-backend replace 10.1.96.5 10.1.96.7   # new must be ready; one atomic swap
```

Every change validates the generated Caddyfile, then runs `caddy reload`. If anything fails,
the previous pool and Caddyfile are restored. Don't edit the Caddyfile by hand: `swoovr-backend`
regenerates it from the pool file.

**Replacing a processor (e.g. to upgrade it):**

1. Build the new VM with `./install.sh image-moderation`. Give it the gateway's VPC IP so it
   accepts traffic from Caddy.
2. On the gateway, run `swoovr-backend replace <old-ip> <new-ip>`.
3. Wait over 3 minutes for in-flight jobs to finish, then destroy the old VM.

To take a node out briefly without changing the pool, run `stack.sh … drain` on that node.
Its `/ready` returns 503 and Caddy routes around it. Run `resume` to bring it back.

## Security notes

- TLS ends at Caddy. **Caddy → processor traffic is plain HTTP on the VPC.**
- The single Caddy VM is a single point of failure.
- Caddy is not an auth layer. The processor checks the bearer key on every request.
- SSH (22) is open to any source on every VM. Restrict it with the Vultr firewall if you can.
- If the gateway's VPC IP changes, update each processor. Run `ufw status numbered` to find the
  old rule, `ufw route allow in on <vpc-if> out on br+ from <new-ip> to any port 8080 proto tcp`
  to add the new one, then `ufw delete <n>` to remove the old one.
- Recreating Docker networks changes the bridge names. Rerun `steps/05-networks-and-ufw.sh`
  and delete the stale route rules.
