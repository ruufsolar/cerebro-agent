# Deployment

The deployment mirrors Wattson's current GHCR + Docker Compose VM baseline while keeping
all state and operations separate.

## Topology

- image: `ghcr.io/ruufsolar/cerebro-agent:{main|sha}`;
- compose project/path: `cerebro-agent`, `/etc/cerebro-agent`;
- services: `web`, `worker`, `slack`, `db`;
- health: `127.0.0.1:8010/health`;
- database volume: compose-managed `pgdata`;
- backups: `/var/backups/cerebro-agent`, 14-day initial rotation;
- update check: systemd timer every five minutes;
- environment: `/etc/cerebro-agent/env` and interpolation-only `compose.env`.

The web command migrates Cerebro tables and initializes Procrastinate before serving.
Worker and Slack services wait for web health. Update pulls the image, preserves the outgoing
image as `last-good`, rolls services, and gates success on health. Backups include Cerebro's
own database only, never the replica.

Socket Mode does not require nginx/DNS. If a dashboard or webhook is added later, perform a
separate threat/network review instead of exposing the Phase 0 health server by default.

## Rollback

Set `IMAGE_TAG=last-good` in `/etc/cerebro-agent/compose.env` and run the compose update.
Schema migrations must remain backward-compatible with the previous image for one release;
destructive cleanup is a later migration after rollback safety expires.
