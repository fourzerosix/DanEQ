#!/usr/bin/env bash
# Builds the GitHub Pages site into the directory given as $1 (default: public).
# Needs pandoc. Used by .github/workflows/static.yml; also runnable locally: make site
set -euo pipefail
OUT="${1:-public}"
cd "$(dirname "$0")/.."

VERSION="$(python3 -c 'import re; print(re.search(r"__version__ = \"(.+?)\"", open("daneq/__init__.py").read()).group(1))')"
rm -rf "$OUT"
mkdir -p "$OUT"

cp site/style.css "$OUT/style.css"

# images: copy the logo and screenshots, and build the gallery on the landing page
mkdir -p "$OUT/assets/images"
shopt -s nullglob
for f in assets/images/*.png assets/images/*.jpg; do cp "$f" "$OUT/assets/images/"; done
GALLERY="$(for f in assets/images/daneq-2*.png; do
  b="$(basename "$f")"
  printf '<a href="assets/images/%s"><img loading="lazy" src="assets/images/%s" alt="DanEQ screenshot"></a>\n' "$b" "$b"
done)"
python3 - "$VERSION" "$GALLERY" "$OUT" <<'PY'
import sys
version, gallery, out = sys.argv[1:4]
s = open("site/index.html", encoding="utf-8").read()
open(f"{out}/index.html", "w", encoding="utf-8").write(s.replace("@VERSION@", version).replace("@GALLERY@", gallery))
PY

pandoc README.md -f gfm -s --toc --toc-depth=2 \
  --metadata title="DanEQ documentation" --metadata lang=en \
  -c style.css -B site/nav.html -o "$OUT/docs.html"
pandoc CHANGELOG.md -f gfm -s \
  --metadata title="DanEQ changelog" --metadata lang=en \
  -c style.css -B site/nav.html -o "$OUT/changelog.html"

cp LICENSE "$OUT/LICENSE.txt"
touch "$OUT/.nojekyll"
echo "Built site for DanEQ ${VERSION} in ${OUT}/"
