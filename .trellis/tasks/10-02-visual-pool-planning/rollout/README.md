# Rollout: pool-aware cast planning + resized action images (release 11ad19c)

1. Base check: the three app files in the running container hash to `files.txt` base.
2. Build `Dockerfile` (FROM the running 5887bce7) on the host; run `smoke.py` with `--network none`
   against a staged copy of `private/brand-materials` that has the 12 resized PNGs and the rebuilt
   manifest.
3. No image or copy job running; between slots.
4. Back up the 12 PNGs and the manifest (`*.before-visual-pool-<ts>`), copy the resized PNGs and
   the rebuilt manifest in, rerun the smoke against the live directory.
5. Back up `.env`/`.release.env`, set `APP_IMAGE`, recreate the six app services.

Rollback: restore the 12 PNGs and the manifest from the backups, restore both env files, recreate
the six services. Asset ids of the 12 images change with their content, so their cooldown history
restarts once.
