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
sed "s/@VERSION@/${VERSION}/g" site/index.html > "$OUT/index.html"

pandoc README.md -f gfm -s --toc --toc-depth=2 \
  --metadata title="DanEQ documentation" --metadata lang=en \
  -c style.css -B site/nav.html -o "$OUT/docs.html"
pandoc CHANGELOG.md -f gfm -s \
  --metadata title="DanEQ changelog" --metadata lang=en \
  -c style.css -B site/nav.html -o "$OUT/changelog.html"

cp LICENSE "$OUT/LICENSE.txt"
touch "$OUT/.nojekyll"
echo "Built site for DanEQ ${VERSION} in ${OUT}/"
