# Offline deployment constraint

The company ACR path is not available yet. The last controlled-visual release used the reviewed
offline source-overlay mechanism recorded in
`.trellis/tasks/archive/2026-08/08-13-deploy-todays-changes-production/research/offline-source-overlay.Dockerfile`.

For this task, implementation and checking must treat that artifact as historical reference, not
as a template to mutate in place. The release must:

- build one backend application image from the reviewed commit and locked dependencies;
- prove exact revision/source/base labels, non-root runtime, imports, file manifest and no stale
  `build/lib` or site-packages application copy;
- make backups and immutable rollback image tags before stopping production writers;
- retag all nine backend/migration Compose services to one verified local image ID and use
  `--no-build` during activation;
- keep frontend artifacts outside the production bundle/image;
- preserve `.env`, private brand materials and named volumes by checksum;
- deploy with diversity/OCR flags false, then run the two separately bounded live gates before any
  production activation.

This mechanism is temporary until a company-managed ACR repository and fixed-digest pull path are
available. It must not turn the production server into a general CI builder.
