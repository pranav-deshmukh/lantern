# Publishing lantern-harness to PyPI

The package name `lantern-harness` is confirmed available on PyPI. This has
already been built and smoke-tested successfully as of this writing — the
steps below are what's left to make it publicly `pip install`-able.

## One-time setup

1. Create accounts on both:
   - https://test.pypi.org/account/register/ (for a safe dry run first)
   - https://pypi.org/account/register/ (the real thing)
2. Enable 2FA on both (PyPI requires it for publishing).
3. Create an API token on each site (Account Settings → API tokens → scope it
   to this project once the name exists, or "entire account" for the very
   first upload since the project doesn't exist yet).

## Every release: build, then upload

From `harness/`:

```bash
# Clean any previous build artifacts
rm -rf dist build lantern_harness.egg-info

# Build both the wheel and the source distribution
python -m build

# Validate the metadata before uploading anything
twine check dist/*
```

### Step 1 — always upload to TestPyPI first

```bash
twine upload --repository testpypi dist/*
```

You'll be prompted for credentials — use `__token__` as the username and your
TestPyPI API token (starting with `pypi-`) as the password. Or configure
`~/.pypirc` once so you're never prompted again (see below).

Then verify it actually installs from TestPyPI, in a throwaway virtual
environment:

```bash
python3 -m venv /tmp/testpypi_check
/tmp/testpypi_check/bin/pip install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    lantern-harness
/tmp/testpypi_check/bin/python -c "from harness import Harness; print('works')"
```

The `--extra-index-url` is needed because TestPyPI doesn't mirror real
dependencies like `pydantic` — this tells pip to pull the actual harness
package from TestPyPI but its real dependencies from the real PyPI.

### Step 2 — once TestPyPI install works, upload for real

```bash
twine upload dist/*
```

Then anyone, anywhere, can do:

```bash
pip install lantern-harness
```

## Optional: save your tokens so you're never prompted

Create `~/.pypirc` (keep this file private, never commit it):

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR-REAL-TOKEN-HERE

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-YOUR-TESTPYPI-TOKEN-HERE
```

## Releasing a new version later

1. Bump `version = "0.1.0"` in `pyproject.toml` (PyPI never lets you re-upload
   the same version number, even if you delete the old one).
2. Repeat the build + `twine upload` steps above.
3. Tag the release in git: `git tag v0.1.1 && git push --tags`.

## What NOT to do

- Don't upload directly to real PyPI without testing on TestPyPI first — a
  botched first upload of a version number is permanent; you can't overwrite
  it, only yank it (mark it as broken) and release a new version number.
- Don't commit `~/.pypirc` or any API token to the repo.
- Don't forget to bump the version number — PyPI will simply reject the
  upload if the version already exists.
