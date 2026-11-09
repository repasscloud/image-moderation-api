# Swoovr image moderation — Alpine installer

One installer for every VM. Run it, choose what the machine is, answer that role's questions.

```text
$ ./install.sh
  1) image-moderation   processor + ClamAV (Docker), bound to the VPC IP
  2) caddy              public HTTPS gateway, round-robin to the processors
```

## Network layout

Every VM has two network interfaces. The public one is for administration and outbound
traffic. The VPC one carries traffic between Caddy and the processors. The IPs below are
examples from a `10.19.96.0/20` VPC.

```text
                 Internet
                    │  DNS A record: images.example.com → Caddy public IP
                    ▼
  ┌──────────── caddy-01 ─────────────┐
  │ eth0  public IP   ← 80, 443, 22   │
  │ eth1  10.19.96.10/20 (VPC)        │
  └──────────────┬────────────────────┘
                 │  HTTP :8080 over the VPC (10.19.96.0/20)
        ┌────────┴────────┐
  img-app-01          img-app-02
  eth1 10.19.96.21    eth1 10.19.96.22   ← :8080 bound here only
  eth0 public IP      eth0 public IP     ← SSH 22, image pulls, ClamAV updates
```

- **Caddy's public IP** is where the DNS record points. Port 443 serves HTTPS, port 80 is
  needed for certificate issuance and renewal, and 22 is SSH.
- **Caddy's VPC IP** is how it reaches each processor on `:8080`. Caddy needs no firewall rule
  for this because outbound traffic is allowed by default.
- **Each processor publishes 8080 only on its VPC IP.** It can't be reached through the
  public IP even if a firewall rule were wrong. The processor's public IP is used for SSH,
  Docker image pulls, ClamAV signature updates and Arachnid API calls.
- **All VMs must be in the same VPC.** Caddy's VPC IP must fall inside the processors'
  subnet. Run `ip -4 addr` on each VM before installing to confirm the VPC interface actually
  has its address. Attaching it in the Vultr portal isn't always enough.

### How a processor lets Caddy in

Docker forwards published ports onto its own bridge network, so a normal `ufw allow` rule
doesn't apply to them. The installer adds a **route** rule instead. The interface and subnet
are derived from the bind IP you enter. For example, `10.19.96.21` on `eth1` with a `/20`
prefix gives:

```sh
# gateway question left blank: allow the whole VPC subnet
ufw route allow in on eth1 out on br+ from 10.19.96.0/20 to any port 8080 proto tcp

# gateway question answered with 10.19.96.10: allow Caddy only
ufw route allow in on eth1 out on br+ from 10.19.96.10 to any port 8080 proto tcp
```

The prefix is read from the interface, so a `/24` or `/16` VPC works the same way. Leaving
the gateway question blank also lets you `curl :8080/ready` from other VPC machines while
troubleshooting. Entering the gateway IP is tighter.

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

### Adding and removing machines

The processors Caddy sends traffic to are called the **pool**. The pool is a plain list of
VPC IPs in `/etc/swoovr-caddy/backends`. You change it with `swoovr-backend` on the gateway:

```sh
swoovr-backend list                           # each machine and its /ready status
swoovr-backend add 10.19.96.23                # only adds it if /ready returns 200 (--force overrides)
swoovr-backend remove 10.19.96.21             # refuses to remove the last machine
swoovr-backend replace 10.19.96.21 10.19.96.23   # swap one machine for another in a single reload
```

What each command does:

- **`list`** shows every machine in the pool and the HTTP code its `/ready` returns right
  now. `200` means it's taking traffic. `503` means it's draining or its ClamAV signatures
  are stale. `000` means it can't be reached, so check the VPC and that processor's UFW rule.
- **`add <ip>`** puts a new machine into the round-robin. It first checks that the machine's
  `/ready` returns 200, so a half-installed node or one that blocks Caddy is caught before any
  traffic goes to it. `--force` skips the check. Caddy then keeps the machine out of rotation
  until its health checks pass.
- **`remove <ip>`** takes a machine out of the round-robin. It refuses to remove the last
  machine, because that would leave the domain with nothing to serve it.
- **`replace <old> <new>`** is `add` and `remove` in one step. The new machine must be ready,
  and the swap happens in a single reload, so the pool never shrinks during the change.

Every command follows the same safety steps:

```text
 write new pool + Caddyfile to temp files
          │
          ▼
 caddy validate ── fails ──▶ discard temp files, nothing changes
          │ ok
          ▼
 swap files in, caddy reload ── fails ──▶ put the previous pool + Caddyfile back
          │ ok
          ▼
 new pool live, no restart. Requests already in flight get up to 200s
 to finish on the old config (jobs can take 180s)
```

So removing a machine doesn't cut off its current jobs. Don't edit `/etc/caddy/Caddyfile` by
hand: `swoovr-backend` regenerates it from the pool file and would overwrite your edits.

**Replacing a processor (e.g. to upgrade it):**

1. Build the new VM with `./install.sh image-moderation`. Give it the gateway's VPC IP so it
   accepts traffic from Caddy.
2. On the gateway, run `swoovr-backend replace <old-ip> <new-ip>`.
3. Wait over 3 minutes for in-flight jobs to finish, then destroy the old VM.

```text
 before:   caddy ──▶ .21, .22
              │
              │  swoovr-backend replace 10.19.96.21 10.19.96.23
              ▼
 during:   caddy ──▶ .23, .22    new requests
                 ╌╌▶ .21          only finishes jobs it already had (up to 200s)
              │
              │  wait 3+ minutes, then destroy .21
              ▼
 after:    caddy ──▶ .23, .22
```

To take a node out briefly without changing the pool, run `stack.sh … drain` on that node.
Its `/ready` returns 503 and Caddy routes around it. Run `resume` to bring it back.

## What has been tested

These checks were run in **Alpine Linux 3.22** containers (BusyBox `ash`, the same shell the
VMs use):

| Area | Result |
| --- | --- |
| `shellcheck -s sh` on every script | Clean |
| `swoovr-backend` against a real Caddy (Alpine package) and two dummy backends | `add`, `remove` and `replace` each reloaded the live config, confirmed through Caddy's admin API. Adding a duplicate or unreachable machine and removing the last one were refused with nothing changed. The lock was released after every command. |
| Generated Caddyfile | `grace_period` live at 200s. Only `POST /v1/process` reaches a backend. `GET /v1/process` and `/ready` return 404. |
| Installer prompts, driven through a terminal | Public, non-local and out-of-subnet IPs, a short `API_KEY`, an IP given as the domain, duplicate backends, and cancelling at the summary all stop the installer before anything changes. |
| IP helpers | Validation, private-range checks and subnet maths (e.g. `10.19.96.37/20` → `10.19.96.0/20`) |
| `bundle.sh` | The tarball contains the installer and the `deploy/vultr` stack files. |

### UAT on real Vultr VMs

Two processors and one gateway, on Alpine 3.24 in Sydney (4 vCPU / 8 GB processors):

| Check | Result |
| --- | --- |
| Full install of both roles | Passed once three bugs this run found were fixed: the kernel upgrade breaking Docker until a reboot, stale ClamAV signatures on a fresh volume, and `/usr/local/sbin` missing on the gateway |
| HTTPS | Let's Encrypt certificate issued automatically. HTTP redirects to HTTPS. |
| Public surface | `/ready`, `/health` and `GET /v1/process` return 404. An unauthenticated POST returns 401. `:8080` is unreachable on public IPs. |
| Authenticated `POST /v1/process` | HTTP 200 with the full manifest, about 4.5–5s per image from a client in Australia. The bearer token passes through Caddy unchanged. |
| Failover | Draining each processor in turn: its `/ready` went to 503, Caddy routed every request to the other one, and it rejoined after `resume`. |
| Reboot | All three VMs came back healthy without manual steps. |

**Not yet tested:** `swoovr-backend replace` while a job is in flight. This needs a third
processor and will be tested when one is added.

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
