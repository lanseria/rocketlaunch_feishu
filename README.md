# Python CLI Starter Template

A minimal Python command-line application template using Typer and Rich.

## Features

- Basic CLI structure with Typer
- Rich console output
- Python project configuration (pyproject.toml)
- Test setup with pytest

## Installation

```bash
# Create virtual environment
python3 -m venv myenv
python3.12 -m venv myenv
source myenv/bin/activate  # macOS/Linux
# .\myenv\Scripts\Activate.ps1  # Windows

# Install dependencies
pip install -e .
```

## Usage

```bash
cli hello [name]
cli parse-html ./data/html/1.html # for test
cli read-latest-json
cli bitable-list
cli bitable-import-after 1717851480
```

## Development

Run tests:
```bash
pytest
```

## Project Structure

```
src/
  python_cli_starter/
    __init__.py    # Package initialization
    cli.py         # CLI commands
    main.py        # App entry point
tests/             # Test cases
pyproject.toml     # Project configuration
```

## License

MIT
