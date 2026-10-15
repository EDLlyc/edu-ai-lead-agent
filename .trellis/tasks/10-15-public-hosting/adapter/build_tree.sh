#!/usr/bin/env bash
# Assemble the exhibit adapter source exactly like connect_live.py does (pinned release + reviewed
# overlay files), but take the overlays from a COMMIT, never from the working tree.
# Usage: build_tree.sh <repo-root> <overlay-commit> <outdir>
set -Eeuo pipefail
repo="$1"; commit="$2"; out="$3"
release=f06694a54a6507054b2de4b69b06785ffb3780d2
overlays=(
  app/schemas/visitor_display.py app/infrastructure/db/visitor_display.py
  app/application/services/visitor_display.py app/api/v1/routes/visitor_display.py
  app/visitor_display_main.py app/api/v1/routes/visitor_display_review.py
  app/api/v1/routes/visitor_display_human_pick.py app/infrastructure/db/visitor_improvement.py
  app/application/services/visitor_improvement.py app/infrastructure/db/visitor_moments.py
  app/application/services/visitor_moments.py app/infrastructure/visitor_review_store.py
  app/infrastructure/db/visitor_report.py
)
rm -rf "$out"; mkdir -p "$out"
git -C "$repo" archive --format=tar "$release" backend/app | tar -x -C "$out"
for f in "${overlays[@]}"; do git -C "$repo" show "$commit:backend/$f" > "$out/backend/$f"; done
find "$out" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
(cd "$out/backend" && find app -type f | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1 > ../TREE.sha256)
echo "tree=$(cat "$out/TREE.sha256") release=${release:0:7} overlays=$commit"
