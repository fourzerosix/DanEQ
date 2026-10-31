# DanEQ developer shortcuts
#   make dev          install in editable mode with test and audio extras
#   make test         run the unit tests
#   make check        tests + DSP self-test + a headless demo smoke test
#   make build        build sdist and wheel, then run twine check
#   make site         build the GitHub Pages site into ./public (needs pandoc)
#   make docker       build the Docker image locally
#   make release-check  verify version, changelog and tag are consistent before releasing
#   make bump V=0.4.1 set the version in daneq/__init__.py and add a CHANGELOG stub
#   make clean

PYTHON ?= python3
VERSION := $(shell $(PYTHON) -c 'import re; print(re.search(r"__version__ = \"(.+?)\"", open("daneq/__init__.py").read()).group(1))')

.PHONY: dev test check build site docker release-check bump clean

dev:
	$(PYTHON) -m pip install -e ".[dev,audio]"

test:
	$(PYTHON) -m pytest -q

check: test
	$(PYTHON) -m daneq --selftest | tail -3
	$(PYTHON) -m daneq --list-demos > /dev/null && echo "PASS: list-demos"
	$(PYTHON) -m daneq --export > /dev/null && echo "PASS: export"

build: clean
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*

site:
	bash site/build.sh public
	@echo "Open public/index.html in a browser"

docker:
	docker build -t daneq:$(VERSION) -t daneq:latest .

release-check:
	@echo "version in code: $(VERSION)"
	@grep -q "^## $(VERSION)" CHANGELOG.md || (echo "CHANGELOG.md has no '## $(VERSION)' section" && exit 1)
	@git diff --quiet || (echo "working tree has uncommitted changes" && exit 1)
	@echo "OK. Next: gh release create v$(VERSION) --generate-notes"

bump:
	@test -n "$(V)" || (echo "usage: make bump V=0.4.1" && exit 1)
	sed -i.bak 's/__version__ = ".*"/__version__ = "$(V)"/' daneq/__init__.py && rm -f daneq/__init__.py.bak
	$(PYTHON) - <<'PY'
	import re
	s = open("CHANGELOG.md").read()
	s = s.replace("# Changelog\n", "# Changelog\n\n## $(V)\n- \n", 1)
	open("CHANGELOG.md", "w").write(s)
	PY
	@echo "Now edit CHANGELOG.md, commit, then: make release-check"

clean:
	rm -rf build dist *.egg-info public .pytest_cache
