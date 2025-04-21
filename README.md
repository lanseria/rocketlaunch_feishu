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
cli sync-all
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

## AI Prompt

1. 首先下载 https://www.rocketlaunch.live/?pastOnly=1 html 文件至 ./data/html/lastest.html
2. 然后使用 BeautifulSoup 解析 html 文件，获取所有 rocket 的信息，并保存至 ./data/raw/lastest.json 文件中, 同时添加 timestamp 字段
3. 将数据与多维表格获取的数据对比，通过 timestamp 字段进行对比，如果 timestamp 值相同，则跳过，否则更新数据

要求：参考本有的代码，逻辑拆分有更好的阅读性