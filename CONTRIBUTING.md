# Contributing to Dockerfile Doctor

## Quick Start

```bash
git clone https://github.com/crabsatellite/dockerfile-doctor.git
cd dockerfile-doctor
pip install -e ".[dev]"
pytest
```

## Adding a New Rule

1. Add the rule function in `src/dockerfile_doctor/rules.py` with the `@rule` decorator
2. Use the next available DD number (currently DD081+)
3. Add tests in `tests/test_rules.py` or `tests/test_rules_expanded.py`
4. If auto-fixable, add a handler in `src/dockerfile_doctor/fixer.py` with `@_handler("DD0XX")`

## Running Tests

```bash
pytest                          # Run all tests
pytest -x                      # Stop on first failure
pytest --cov=dockerfile_doctor  # With coverage
pytest -k "test_dd001"         # Run specific test
```

## Code Style

- Pure Python, zero external dependencies (stdlib only)
- Type annotations on all public functions
- Each rule function returns `list[Issue]`
