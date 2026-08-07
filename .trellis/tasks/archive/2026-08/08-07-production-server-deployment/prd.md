# Production Server Deployment

## Goal

Deploy the daily education-content automation to the provided Ubuntu host as a durable,
single-host production service. The deployed system must acquire news, govern events, select a
daily topic, generate copy and an image from the private brand materials, assemble a material
package, and deliver a valid package to the approved Enterprise WeChat group webhook. No frontend
or public web interface is part of this deployment.

## Confirmed Facts

- The target host is Ubuntu 24.04 with 2 vCPU, 7.4 GiB memory, 70 GiB available disk, NTP, Git,
  outbound DNS/HTTPS, and passwordless sudo for the deployment account.
- Docker Engine, Docker Compose, Caddy/Nginx, and an active host firewall are not yet installed.
- The repository is available from GitHub. The current release branch is `main`.
- The existing Compose topology keeps PostgreSQL, MinIO, and the API development port on loopback
  host bindings. The governance, content, and WeCom services require explicit Compose profiles.
- Private brand materials are approximately 219 MiB and are deliberately Git-ignored. They must be
  transferred as a protected release input; the visual-assets manifest and image selector depend on
  them.
- The approved delivery route is the Enterprise WeChat group webhook. It is outbound-only and does
  not require a WeCom callback URL, trusted domain, trusted IP, or self-built-app recipient API.
- The user approved direct automatic delivery after a valid material package exists; production
  configuration must preserve the existing package, image, and provider safety gates.
- The server password and previous development credentials have appeared in conversation history.
  Production must use fresh service-local secrets. The user elected to retain the existing
  `ubuntu` account/password SSH login for this deployment; SSH key-only hardening is deferred.

## Requirements

1. Install and configure Docker Engine and the Compose plugin on the host.
2. Publish a pinned repository release plus the protected private brand-material directory.
3. Use a production-only, untracked environment file with mode `0600`; generate fresh PostgreSQL
   and MinIO credentials. The user authorized a protected one-time copy of the current working
   model-provider, image-provider, and group-webhook credentials so that automation is usable on
   first server startup.
4. Run PostgreSQL and MinIO from persistent named volumes; initialize the private bucket and run
   Alembic migrations and source seeding before workers start.
5. Start the API, acquisition scheduler/worker, governance profile, content profile, and WeCom
   dispatcher in dependency order.
6. Do not deploy the frontend, a reverse proxy, a domain, TLS certificates, or a public API route.
   Keep PostgreSQL, MinIO, the API, schedulers, and workers private or loopback-only.
7. Configure the host firewall to expose only SSH; the application requires outbound HTTPS access
   to news sources, model/image providers, and the Enterprise WeChat webhook. Cloud security-group
   SSH restriction remains an operator responsibility because it cannot be inspected from the VM.
8. Establish PostgreSQL and MinIO backup locations, a retention policy, and a minimally verifiable
   restore path before enabling unattended delivery.
9. Validate container health, database migration revision, private object storage, external API
   egress, and durable WeCom delivery state without logging secrets.

## Out of Scope

- Deploying the frontend, a reverse proxy, a public API endpoint, a domain, or TLS certificates.
- Exposing MinIO, PostgreSQL, worker processes, or development ports to the Internet.
- Adding a WeCom inbound callback or a self-built-app delivery route.
- Weakening provider, SSRF, image validation, or private-storage safeguards.

## Acceptance Criteria

- [ ] The host runs all required Compose profiles with healthy infrastructure and no restart loop.
- [ ] No application HTTP service, database, object store, worker, or scheduler port is publicly
      reachable; administrative inspection uses SSH and loopback-only checks.
- [ ] PostgreSQL and MinIO are persistent and not publicly reachable.
- [ ] Private brand materials are present, readable by the appropriate containers, and the image
      selector can load its manifest.
- [ ] Migrations and source seeding complete before acquisition, governance, content, and delivery
      workers run.
- [ ] Production secrets are fresh, absent from Git/logs, and stored in a permission-restricted
      file or secret store.
- [ ] A valid material package can progress through the configured automatic delivery policy with
      durable status evidence.
- [ ] Backup commands and a rollback/restore procedure are recorded and validated at least at the
      configuration level.
- [ ] The server receives a consistent migration of the cleaned local PostgreSQL state, matching
      MinIO objects, and private brand materials, with the existing selected-topic and delivery
      history intact.

## Deferred Hardening

- The cloud-provider security-group configuration and administrator source CIDRs cannot be
  inspected from the VM. Keep its inbound policy limited to TCP/22 and restrict it to known
  administrator IP ranges when those are stable.
- SSH will stay password-based by the user's explicit choice. Add verified deployment and
  administrator public keys, then disable password/root login, as a separate hardening change.

## Credential Rotation Follow-up

- The user approved a protected one-time copy of the current working model-provider,
  image-provider, and Enterprise WeChat group-webhook credentials for initial production
  availability. Rotate those externally issued credentials after deployment and replace the
  server `.env` values without recording them in Git or task artifacts.

## Backup Decision

- Use host-local backups initially: a daily compressed PostgreSQL dump and MinIO data snapshot in
  a permission-restricted backup directory with seven-day rotation and a recorded restore command.
- This is an operationally acceptable bootstrap for the current low-volume service, but it does not
  survive total server loss. Moving backups to an external destination remains a required future
  hardening item before higher-value or higher-volume production use.

## Data Bootstrap Decision

- Migrate the current cleaned local state to the server rather than initializing an empty database.
  The migration scope includes PostgreSQL, matching private MinIO objects, and Git-ignored brand
  materials.
- Preserve the complete current cleaned database state, the matching private MinIO objects, and
  the scheduled selection/delivery history so the server's next daily run applies the existing
  duplicate-topic rule. A read-only preflight found historical packages and formal delivery rows
  without a reliable test marker; deployment must not infer deletion from timestamps or edit
  business rows. Any later test-data cleanup is a separate audited task.
