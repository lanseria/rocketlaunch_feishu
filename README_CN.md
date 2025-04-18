# Python CLI 项目模板

一个使用 Typer 和 Rich 的最小化 Python 命令行应用模板。

## 功能特性

- 基于 Typer 的基本 CLI 结构
- 使用 Rich 的终端美化输出
- Python 项目配置 (pyproject.toml)
- 集成 pytest 测试框架

## 安装

```bash
# 创建虚拟环境
python3 -m venv myenv
python3.12 -m venv myenv
source myenv/bin/activate  # macOS/Linux
# .\myenv\Scripts\Activate.ps1  # Windows

# 安装依赖
pip install -e .
```

## 使用方式

```bash
cli hello [名字]
```

## 开发指南

运行测试：
```bash
pytest
```

## 项目结构

```
src/
  python_cli_starter/
    __init__.py    # 包初始化文件
    cli.py         # CLI 命令定义
    main.py        # 应用入口
tests/             # 测试用例
pyproject.toml     # 项目配置文件
```

## 许可证

MIT 开源协议
