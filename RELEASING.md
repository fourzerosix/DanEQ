# Releasing DanEQ

Publishing a GitHub Release does everything:

| Workflow file | What it does | Result |
| --- | --- | --- |
| `.github/workflows/python-publish.yml` | tests on Linux and macOS, checks tag == version, builds, `twine check`, publishes | https://pypi.org/project/daneq/ and wheel + sdist attached to the release |
| `.github/workflows/docker-deploy.yml` | builds a multi-arch image (amd64, arm64) and pushes it | `fourzerosix/daneq` on Docker Hub and `ghcr.io/fourzerosix/daneq`, tags `X.Y.Z`, `X.Y`, `latest` |
| `.github/workflows/static.yml` | builds the site from `site/` plus README and CHANGELOG | https://fourzerosix.github.io/DanEQ/ |
| `.github/workflows/ci.yml` | tests on every push and pull request (Linux, macOS) | green badge |

## One-time setup

1. **PyPI trusted publishing** (no token needed). Go to https://pypi.org/manage/account/publishing/ and add a
   *pending publisher*: project `daneq`, owner `fourzerosix`, repository `DanEQ`, workflow `python-publish.yml`,
   environment `pypi`.
2. **GitHub environment**: repo Settings > Environments > New environment named `pypi`. Leave "Deployment branches and tags" on *No restriction* (or add a tag rule `v*`), because release runs come from a tag.
3. **GitHub Pages**: repo Settings > Pages > Build and deployment > Source: **GitHub Actions**. Then Settings > Environments > `github-pages` > Deployment branches and tags > add a **tag** rule `v*` (the default only allows `main`, which blocks release-triggered deploys).
4. **Docker Hub** (optional but matches your other projects): create an access token at
   https://hub.docker.com/settings/security, then in the repo Settings > Secrets and variables > Actions add
   `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. Without them only GHCR is published.
5. **GHCR visibility**: after the first push, open the package at https://github.com/fourzerosix?tab=packages,
   Package settings, and set it to Public.
6. Settings > Actions > General > Workflow permissions: leave the default; the workflows request what they need.

## Every release

```bash
make bump V=0.4.1              # edits daneq/__init__.py and adds a CHANGELOG section
$EDITOR CHANGELOG.md           # describe the changes
git commit -am "Release 0.4.1" && git push
make release-check             # version, changelog and clean tree are consistent
gh release create v0.4.1 --generate-notes      # or use the GitHub web UI: Releases > Draft a new release
```

The tag must be `v` plus the version in `daneq/__init__.py`. The PyPI workflow refuses to publish if they differ.
Watch progress in the Actions tab. PyPI never accepts the same version twice, so a failed publish needs a new
version number (for example 0.4.2).

## If something fails

| Symptom | Fix |
| --- | --- |
| PyPI step: "invalid-publisher" | The pending publisher on PyPI does not match owner, repo, workflow name (`python-publish.yml`) or environment (`pypi`) exactly |
| "Tag vX does not match version" | Bump `daneq/__init__.py`, push, delete the release and tag, create them again |
| Docker Hub login fails | Re-create the token; the username is your Docker Hub login, not your email |
| Pages: "Get Pages site failed" or 404 | Settings > Pages > Source must be "GitHub Actions" |
| Pages: "Tag vX is not allowed to deploy to github-pages" | Add a tag rule `v*` under Settings > Environments > github-pages |
| The macOS test job fails | The release is blocked on purpose; fix the test, bump the version, release again |
| Need the logs | `gh run list --limit 5` then `gh run view RUN_ID --log-failed` |
| Workflows do not start | The release must be *published* (not a draft), and created by you, not by another workflow using `GITHUB_TOKEN` |

## Re-releasing after a failed run

If PyPI never received the version (the publish job did not run), you can delete the release and tag and recreate them.
If anything was already published (for example the Docker image), bump to the next patch version instead.
After a fix: `make bump V=0.4.2`, edit `CHANGELOG.md`, commit, push, `gh release create v0.4.2 --generate-notes`.

## README images

Use absolute URLs for images in `README.md` (`https://raw.githubusercontent.com/fourzerosix/DanEQ/main/...`); relative paths
work on GitHub but break on PyPI and Docker Hub, which render the same README.
