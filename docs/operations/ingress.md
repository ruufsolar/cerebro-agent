# Public ingress for bank-movement events

Cerebro's only public surface: `POST https://cerebro.ruuf.cl/integrations/bank-movements`,
which the monolith calls with an Authentik M2M token when a bank payment arrives.

The decision and its boundaries are [ADR-011](../adr/011-public-bank-movement-ingress.md).
This page is how to set it up, what to configure, how to check it works, and how to take it
away again.

## What exists

```text
monolith ──POST /integrations/bank-movements──┐
                Authorization: Bearer <JWT>   │
                                              ▼
                            cerebro.ruuf.cl (static Azure IP)
                                              │  NSG: 443 from approved sources
                                              │       80 from the Internet, ACME only
                                              ▼
                                       caddy (Compose)
                                       TLS, auto-renewal
                                       one method, one path
                                              │
                                              ▼
                                       web:8000  ──validates iss/aud/azp/exp
                                              │   against auth.ruuf.solar
                                              ▼
                                     202 Accepted, queued
```

Nothing else is reachable. `/health`, `/ready`, `/docs`, `/openapi.json`, the workers,
PostgreSQL, and SSH have no public route; the proxy answers 404 for every other path and
method, and the network security group denies their ports by name as well as by default.

## One switch, in three places

The ingress is off unless a hostname is configured, and the same hostname has to appear in
all three places or the address and the listener end up on different names:

| Where | What | Effect when empty |
|---|---|---|
| `ingress_hostname` in `terraform.tfvars` | the Azure address, inbound rules, optional DNS record | no public IP, no inbound rule |
| `CEREBRO_PUBLIC_HOSTNAME` in the approved `.env`, seeded to Key Vault as `public-hostname` | the Caddy container and its certificate | Compose profile stays empty; Caddy is not in the project |
| the DNS record for that name | what the certificate authority and the monolith resolve | Caddy cannot obtain a certificate |

## External setup, before any of this is applied

These are other people's systems. Do them first; the rest is not useful without them.

### 1. Authentik: the client the monolith uses

Ask the platform owner (the same owner as Cerebro's `agents-cerebro` M2M client) to create
a dedicated OAuth2/OIDC **machine-to-machine** provider and application for this call, and
to bring back three values. Do not reuse a client that already serves another integration:
the client id is how Cerebro decides who is allowed to post payments.

| Value | Cerebro setting | Note |
|---|---|---|
| Issuer | `CEREBRO_BANK_INGESTION_ISSUER` | Authentik's `iss`, the provider URL with its trailing slash, e.g. `https://auth.ruuf.solar/application/o/<slug>/` |
| Audience | `CEREBRO_BANK_INGESTION_AUDIENCE` | what the token's `aud` actually carries |
| Client id | `CEREBRO_BANK_INGESTION_CLIENT_ID` | the monolith's client, matched against `azp` |

Two things to confirm rather than assume, because Authentik can be configured either way and
guessing produces a token that validates in staging and is refused in production:

- **Issuer mode, and whose slug it is.** Per-provider (the default) makes `iss` end in the
  slug of the provider that *minted* the token — the monolith's, not Cerebro's, because the
  monolith is the one calling. Global mode makes every provider share one issuer. Either
  way the value Cerebro compares against is copied from a real token, never constructed
  from Cerebro's own name.
- **What `aud` holds.** In Authentik's default per-provider mode a client-credentials token
  carries the requesting client's own id in `aud`, so the audience and the client id may be
  the same string. That is fine. What matters is that both are checked.

The quickest way to settle both: have the platform owner mint one token with the new client
and decode it (`https://auth.ruuf.solar/application/o/token/`, `grant_type=client_credentials`).
Read `iss`, `aud`, and `azp` off the payload. Never paste the token itself into a ticket,
Slack, or a chat with an AI assistant.

Cerebro reaches `auth.ruuf.solar` for the signing keys through the existing NAT egress; no
new outbound rule is needed.

### 2. DNS: where `ruuf.cl` is hosted

- **In Azure DNS:** set `dns_zone_name` and `dns_zone_resource_group_name` and Terraform
  creates the A record.
- **Anywhere else:** leave them empty, apply, then give the zone owner
  `terraform output -raw ingress_public_ip` and have them create
  `A cerebro.ruuf.cl -> <that address>` with a short TTL.

Either way the name must resolve **before** activation. Caddy asks for the certificate on
its first start; a name that does not resolve yet leaves it retrying on a backoff.

### 3. The monolith's egress addresses

Ask the platform owner which addresses the monolith calls out from, and put them in
`ingress_allowed_source_ranges`. `["Internet"]` works and is the default, but it means the
application-level token check is the only thing standing between a scanner and the endpoint.
Narrow it as soon as the addresses are known. Port 80 stays open to the Internet either way,
because a certificate authority validates from vantage points nobody can enumerate.

## Turning it on

Run from `infra/terraform`, in this order.

```bash
# 1. The address and the inbound rules.
#    Review the plan for: one public IP, one AllowHttpsInbound, one AllowAcmeHttpInbound,
#    three explicit Deny rules, and the NIC gaining a public_ip_address_id.
terraform plan -out=cerebro-prod.tfplan
terraform apply cerebro-prod.tfplan
terraform output ingress_dns_record

# 2. The record, if Terraform does not manage it. Then confirm it resolves:
dig +short cerebro.ruuf.cl

# 3. The runtime configuration. Add to the approved .env:
#      CEREBRO_PUBLIC_HOSTNAME=cerebro.ruuf.cl
#      CEREBRO_ACME_EMAIL=<a mailbox the CA can reach>
#      CEREBRO_BANK_INGESTION_ISSUER=<the iss from the decoded token, trailing slash included>
#      CEREBRO_BANK_INGESTION_AUDIENCE=<from the decoded token>
#      CEREBRO_BANK_INGESTION_CLIENT_ID=<the monolith's client>
#    The seeder refuses a hostname without all four of the others.
./scripts/seed-secrets.sh --vault-name "$(terraform output -raw key_vault_name)" \
  --env-file ../../.env

# 4. Start it. Activation now also waits for the proxy to listen before reporting success.
./scripts/activate.sh
```

Key Vault gains five entries: `public-hostname`, `acme-contact-email`,
`bank-ingestion-issuer`, `bank-ingestion-audience`, `bank-ingestion-client-id`. None is a
credential; the vault is simply how non-secret runtime configuration reaches the private VM.

## Validating it

From a workstation, with no credential:

```bash
HOST=cerebro.ruuf.cl

# The certificate is real, matches the name, and has a renewal window left on it.
echo | openssl s_client -connect "$HOST:443" -servername "$HOST" 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates

# Unauthenticated requests are refused before anything reads them.
curl -s -o /dev/null -w '%{http_code}\n' -X POST "https://$HOST/integrations/bank-movements" \
  -H 'Content-Type: application/json' -d '{}'          # expect 401

# Nothing operational is exposed.
for path in /health /ready /docs /openapi.json /; do
  printf '%-16s %s\n' "$path" "$(curl -s -o /dev/null -w '%{http_code}' "https://$HOST$path")"
done                                                    # expect 404 for every one

# The endpoint is POST-only.
curl -s -o /dev/null -w '%{http_code}\n' "https://$HOST/integrations/bank-movements"  # 404

# Ports that must not answer.
for port in 22 5432 5434 8000 8010; do
  printf '%-6s %s\n' "$port" "$(nc -z -w 3 "$HOST" "$port" && echo OPEN || echo closed)"
done                                                    # expect closed for every one
```

On the VM, through Run Command:

```bash
# Configuration reached the runtime, and Authentik's key set is reachable from here.
az vm run-command invoke --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts 'cd /etc/cerebro-agent && docker compose --env-file compose.env exec -T web \
    python -m cerebro.ops.preflight --profile pilot'
```

The `bank_ingestion` check appears only when the ingress is on. It reports `incomplete` when
something is enabled but unconfigured, `jwks_http_<code>` when Authentik answers but not with
keys, and `failed_<ExceptionType>` when it cannot be reached at all — a wrong issuer and a
blocked egress look different, on purpose.

Once the monolith has a client, ask its owner to send one synthetic event and confirm a
`202`. Do not construct that request yourself with a copied token.

## Rolling it back

The ingress is one switch, so removing it is one reseed and one activation. Nothing about
Slack, the workers, or the database is involved.

```bash
# 1. Turn off the listener. Set CEREBRO_PUBLIC_HOSTNAME= (empty) in the approved .env.
./scripts/seed-secrets.sh --vault-name "$(terraform output -raw key_vault_name)" \
  --env-file ../../.env
./scripts/activate.sh
```

The VM writes an empty `COMPOSE_PROFILES`, the next update removes the Caddy container as an
orphan, and `CEREBRO_BANK_INGESTION_ENABLED` returns to false. Cerebro keeps running on
Slack exactly as before. The address and the inbound rules still exist but nothing listens.

```bash
# 2. Optional, to give the address back as well: set ingress_hostname = "" and apply.
terraform plan -out=cerebro-prod.tfplan && terraform apply cerebro-prod.tfplan
```

That removes the public IP, both inbound allow rules, and the A record if Terraform manages
it. Reversing it later issues a **new** address, so leave step 2 undone if the ingress is
likely to come back; an unattached listener costs a few dollars a month and a re-issued
address costs a DNS change coordinated with the monolith.

To take away only the ability to call, without touching the runtime, narrow
`ingress_allowed_source_ranges` to an address that is not the monolith's and apply. Traffic
is refused at the Azure edge and the certificate keeps renewing over port 80.

## The parts that do not fail over

- One VM and one Caddy: an update, a reboot, or a host failure is a window of refused
  connections. The monolith must retry; the `202` contract assumes it.
- Certificate renewal depends on port 80 reaching this address from the Internet. Narrowing
  that rule, or losing the DNS record, breaks renewal silently 30 days before it matters.
- Let's Encrypt rate limits apply per registered domain. Repeatedly destroying and recreating
  the deployment can exhaust them; the certificates live on the retained data disk precisely
  so that ordinary container replacement never re-issues.
