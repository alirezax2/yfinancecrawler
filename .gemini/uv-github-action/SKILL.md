# uv GitHub Actions

## Purpose

Use `uv` as the Python package manager and environment manager in GitHub Actions.

This skill defines the standard approach for:

* Installing uv
* Setting up Python
* Installing project dependencies
* Running tests and commands
* Using the uv lockfile
* Caching dependencies
* Running matrix builds
* Working with private GitHub dependencies
* Building and publishing Python packages

Follow the official Astral uv GitHub Actions integration guidance.

## Standard Approach

Use the official:

```yaml
astral-sh/setup-uv
```

GitHub Action.

Do not install uv with `pip`, `curl`, or an ad-hoc shell installer when `setup-uv` can be used.

The official action installs uv, adds it to `PATH`, and supports uv's cache integration.

## Basic Workflow

For a normal Python project using `pyproject.toml` and `uv.lock`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Install uv
        uses: astral-sh/setup-uv@v9
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install

      - name: Install dependencies
        run: uv sync --locked --all-extras --dev

      - name: Run tests
        run: uv run pytest
```

Prefer the project's `uv.lock` as the source of truth for CI dependency resolution.

## Pin GitHub Actions

For production repositories, pin GitHub Actions to specific versions or commit SHAs rather than relying on mutable references.

Example:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9
  with:
    enable-cache: true
```

The official uv documentation recommends pinning the uv version for reproducibility.

If using a version rather than a SHA:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v9
  with:
    version: "0.12.10"
    enable-cache: true
```

When reproducibility is important, explicitly specify the uv version.

## Python Version

### Preferred: project-managed Python

If the project's Python version is defined by `.python-version` or `pyproject.toml`, allow uv to install the required Python:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v9
  with:
    enable-cache: true

- name: Set up Python
  run: uv python install
```

This respects the project's Python version configuration.

### Using `.python-version`

Example:

```text
.python-version
```

```text
3.12
```

Then:

```yaml
- name: Set up Python
  run: uv python install
```

### Using `actions/setup-python`

If GitHub's Python installation cache is preferable, use `actions/setup-python`:

```yaml
- name: Set up Python
  uses: actions/setup-python@v7
  with:
    python-version-file: ".python-version"

- name: Install uv
  uses: astral-sh/setup-uv@v9
  with:
    enable-cache: true
```

The official documentation notes that `setup-python` can be faster because GitHub caches Python versions on runners.

## Dependency Installation

For projects managed by uv:

```yaml
- name: Install dependencies
  run: uv sync --locked --all-extras --dev
```

Use:

```text
--locked
```

in CI.

This ensures CI uses the committed `uv.lock` rather than silently modifying the lockfile.

Do not use:

```bash
uv sync
```

as the default CI command when reproducibility is required.

## Running Commands

Run project commands through:

```bash
uv run
```

Examples:

```yaml
- name: Run tests
  run: uv run pytest

- name: Run lint
  run: uv run ruff check .

- name: Run formatter check
  run: uv run ruff format --check .

- name: Run type checking
  run: uv run mypy .

- name: Run application
  run: uv run python -m myapp
```

Do not manually activate `.venv` in GitHub Actions.

Prefer:

```bash
uv run ...
```

because uv automatically uses the project's environment.

## Caching

Enable uv's built-in cache support:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v9
  with:
    enable-cache: true
```

This is the preferred caching mechanism for normal GitHub-hosted runners.

Do not add a separate `actions/cache` workflow for uv unless there is a specific reason to manage the cache manually.

## Cache Invalidation

The dependency lockfile should determine when the dependency cache needs to change.

The cache should effectively be associated with:

```text
OS
+
uv
+
uv.lock
```

Changing `uv.lock` should cause dependencies to be refreshed.

## Matrix Testing

For testing multiple Python versions, use a GitHub Actions matrix.

Example:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    strategy:
      matrix:
        python-version:
          - "3.11"
          - "3.12"
          - "3.13"

    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Install uv and set Python
        uses: astral-sh/setup-uv@v9
        with:
          python-version: ${{ matrix.python-version }}
          enable-cache: true

      - name: Install dependencies
        run: uv sync --locked --all-extras --dev

      - name: Run tests
        run: uv run pytest
```

`setup-uv` can set the Python version for each matrix entry.

## Recommended CI Structure

For most projects, use this sequence:

```text
Checkout
   ↓
Install uv
   ↓
Set up Python
   ↓
uv sync --locked
   ↓
Lint / Type Check
   ↓
Tests
   ↓
Build
```

Example:

```yaml
steps:
  - name: Checkout
    uses: actions/checkout@v7

  - name: Install uv
    uses: astral-sh/setup-uv@v9
    with:
      enable-cache: true

  - name: Set up Python
    run: uv python install

  - name: Install dependencies
    run: uv sync --locked --all-extras --dev

  - name: Lint
    run: uv run ruff check .

  - name: Test
    run: uv run pytest

  - name: Build
    run: uv build
```

## Build Artifacts

Build Python packages with:

```yaml
- name: Build
  run: uv build
```

The resulting distributions are placed in:

```text
dist/
```

Upload them when they need to be passed between jobs:

```yaml
- name: Upload distributions
  uses: actions/upload-artifact@v7
  with:
    name: dist
    path: dist/
```

## Publishing to PyPI

When publishing packages, prefer **PyPI Trusted Publishing** rather than storing a long-lived PyPI token.

Separate the workflow into:

```text
build
  ↓
artifact
  ↓
publish
```

The build job should not receive publishing permissions.

The publishing job should receive only the permissions required for publishing, including:

```yaml
permissions:
  id-token: write
```

This reduces the supply-chain attack surface.

Example:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read

    steps:
      - name: Checkout
        uses: actions/checkout@v7
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@v9
        with:
          enable-cache: false

      - name: Build
        run: uv build

      - name: Upload distributions
        uses: actions/upload-artifact@v7
        with:
          name: dist
          path: dist/

  publish:
    needs:
      - build

    runs-on: ubuntu-latest

    permissions:
      id-token: write

    steps:
      - name: Install uv
        uses: astral-sh/setup-uv@v9
        with:
          enable-cache: false

      - name: Download distributions
        uses: actions/download-artifact@v8
        with:
          name: dist
          path: dist/

      - name: Publish
        run: uv publish
```

Configure the corresponding PyPI Trusted Publisher separately in PyPI.

## Private GitHub Dependencies

If the project depends on private GitHub repositories, configure authentication before running `uv sync`.

Store the access token as a GitHub repository secret.

Example:

```yaml
- name: Authenticate GitHub CLI
  run: echo "${{ secrets.MY_PAT }}" | gh auth login --with-token

- name: Configure Git credentials
  run: gh auth setup-git

- name: Install dependencies
  run: uv sync --locked
```

The token should have only the permissions required to read the private repositories.

Do not hard-code tokens in:

* `pyproject.toml`
* `uv.lock`
* workflow files
* shell scripts
* source code

The official uv documentation recommends using a PAT and Git credential helper for private GitHub dependencies.

## `uv pip` Projects

Prefer the uv project interface:

```bash
uv sync
uv run
```

for projects using `pyproject.toml` and `uv.lock`.

Only use the `uv pip` interface when the project intentionally follows a requirements/virtual-environment workflow.

Example:

```yaml
- name: Install dependencies
  run: uv pip install -r requirements.txt
```

By default, `uv pip` expects a virtual environment.

If intentionally installing into the system Python environment, use:

```yaml
- name: Install dependencies
  run: uv pip install --system -r requirements.txt
```

or configure:

```yaml
env:
  UV_SYSTEM_PYTHON: 1
```

Do not use `UV_SYSTEM_PYTHON` for normal uv project workflows unless there is a specific reason.

## CI Rules

Always follow these rules:

### Do

* Use `astral-sh/setup-uv`.
* Pin uv for reproducible CI.
* Commit `uv.lock`.
* Use `uv sync --locked`.
* Use `uv run` for project commands.
* Enable uv caching on normal CI jobs.
* Use matrix builds when multiple Python versions need testing.
* Use Trusted Publishing for PyPI when possible.
* Keep publishing permissions isolated from build/test jobs.
* Store credentials in GitHub Secrets.

### Do not

* Install uv with `pip` when `setup-uv` is available.
* Run `pip install` for project dependencies in a uv-managed project.
* Modify `uv.lock` during CI.
* Manually activate `.venv`.
* Use long-lived PyPI credentials when Trusted Publishing is available.
* Put GitHub/PyPI credentials in source files.
* Give build/test jobs unnecessary write permissions.

## Standard Template

Use this as the default starting point:

```yaml
name: CI

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Install uv
        uses: astral-sh/setup-uv@v9
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install

      - name: Install dependencies
        run: uv sync --locked --all-extras --dev

      - name: Lint
        run: uv run ruff check .

      - name: Test
        run: uv run pytest
```

## Decision Rule

When adding or modifying a GitHub Actions workflow in a uv-managed Python project:

```text
Is this a uv project?
        │
       YES
        │
        ▼
Use setup-uv
        │
        ▼
Use project's Python version
        │
        ▼
uv sync --locked
        │
        ▼
uv run <command>
```

Do not introduce pip-based dependency installation unless the project explicitly requires the `uv pip` workflow.

## Reference

Use the official Astral documentation as the authoritative reference for GitHub Actions integration:

[uv — Using uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/?utm_source=chatgpt.com)
