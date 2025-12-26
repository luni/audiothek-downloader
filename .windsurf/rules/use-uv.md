---
trigger: always_on
---
- All Python dependencies must be installed, synchronized, and locked using uv.
- Never use pip, pip-tools, or poetry directly for dependency management.
- Check pyproject.toml for rules and used toolset.
- use uv run make test to run tests.