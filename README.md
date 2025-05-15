# Rocket Launch Sync to Feishu (NextSpaceflight Edition)

一个命令行工具，用于自动从 NextSpaceflight.com 抓取火箭发射数据，并将其同步到飞书多维表格。

## ✨ 功能特性

-   **数据抓取**: 从 [NextSpaceflight.com](https://nextspaceflight.com/launches/past/) 抓取历史火箭发射数据。
    -   支持抓取所有历史发射页面或仅抓取最新页面。
-   **数据解析**: 解析 HTML 数据，提取发射任务、火箭型号、发射地点、发射时间、发射状态等关键信息。
-   **本地存储**: 将解析后的数据以 JSON 格式保存到本地。
-   **飞书同步**:
    -   将新的发射数据同步到指定的飞书多维表格。
    -   通过与飞书已有数据对比，实现增量更新，避免重复添加。
    -   支持在添加到飞书前进行二次存在性检查（可选）。
    -   支持中断续传，在大量数据同步过程中意外中断后可从断点继续。
-   **灵活的工作流**:
    -   数据抓取与解析 (`fetch-data`)
    -   数据准备与去重 (`prepare-feishu-sync`)
    -   数据执行同步 (`execute-feishu-sync`)
    -   一键执行完整同步流程 (`run-daily-sync-flow`)，方便与外部调度器（如 cron）集成。

## 🚀 快速开始

### 1. 环境准备

-   Python 3.9+
-   Poetry (推荐用于依赖管理和打包) 或 pip

### 2. 安装

**使用 Poetry:**

```bash
git clone https://github.com/lanseria/rocketlaunch_feishu.git # 替换为您的仓库地址
cd rocketlaunch_feishu
poetry install
```

**或者使用 pip (如果项目已发布或直接从源码安装):**

```bash
git clone https://github.com/lanseria/rocketlaunch_feishu.git # 替换为您的仓库地址
cd rocketlaunch_feishu
pip install .
# 或者，对于可编辑模式安装 (推荐开发时使用)
# pip install -e .
```

### 3. 配置

复制环境变量配置文件，并根据您的飞书应用和多维表格信息进行修改：

```bash
cp .env.example .env
vim .env # 或者使用您喜欢的编辑器编辑 .env 文件
```

您需要在 `.env` 文件中配置以下飞书凭证和多维表格ID：

-   `FEISHU_APP_ID`: 飞书应用的 App ID
-   `FEISHU_APP_SECRET`: 飞书应用的 App Secret
-   `BITABLE_APP_TOKEN`: 飞书多维表格的 App Token (Base Token)
-   `BITABLE_TABLE_ID`: 目标数据表的 Table ID
-   `BITABLE_VIEW_ID` (可选): 如果您希望操作特定视图，请配置此项。

确保您的飞书多维表格包含以下列（或根据实际情况调整代码中的字段映射）：
*   `Rocket Model` (文本)
*   `发射任务名称` (文本)
*   `发射位` (文本) - 用于存储组合后的发射台和地点
*   `发射日期时间` (日期) - 用于存储毫秒级时间戳 (支持1970年前的负时间戳)
*   `Source` (文本) - 将固定为 `nextspaceflight.com`
*   `发射状态` (单选或文本) - 例如: 发射成功, 发射失败, 部分成功, 计划中, 状态未知
*   `发射任务描述` (多行文本) - 当前版本默认为 "N/A"
*   `发射日期文本` (文本) - 用于存储标准格式的日期时间字符串

## 🛠️ 使用方法

该工具提供了一个名为 `rocketlaunch-feishu` (或您在 `pyproject.toml` 中定义的脚本名) 的命令行接口。

### 数据处理流程命令

**步骤 1: 抓取和解析数据**

从 NextSpaceflight.com 抓取数据并保存为 JSON 文件。

```bash
# 抓取最新一页数据
rocketlaunch-feishu fetch-data

# 抓取所有历史数据页面 (可能会非常耗时且产生大量API请求)
rocketlaunch-feishu fetch-data --all-pages

# 指定最大抓取页数 (当 --all-pages 时生效)
rocketlaunch-feishu fetch-data --all-pages --max-pages-nextspaceflight 10

# 指定输出文件 (默认为 data/processed_launches/nextspaceflight.com_processed[_all_pages].json)
rocketlaunch-feishu fetch-data --output-file custom_processed_data.json
```
成功后，数据会保存在例如 `data/processed_launches/nextspaceflight.com_processed.json` 的文件中。

**步骤 2: 准备待同步数据**

将抓取到的数据与飞书多维表格中的现有数据进行比较，生成一个只包含新增记录的 JSON 文件。

```bash
# 使用 fetch-data 的默认输出作为输入
rocketlaunch-feishu prepare-feishu-sync --processed-file data/processed_launches/nextspaceflight.com_processed.json

# 使用自定义的已处理数据文件
rocketlaunch-feishu prepare-feishu-sync --processed-file custom_processed_data.json

# 指定输出的“待同步”文件 (默认为 data/to_sync_launches/<input_filename_base>_to_sync.json)
rocketlaunch-feishu prepare-feishu-sync --processed-file custom_processed_data.json --output-to-sync-file records_to_add.json
```
成功后，待同步数据会保存在例如 `data/to_sync_launches/nextspaceflight.com_processed_to_sync.json` 的文件中。

**步骤 3: 执行同步到飞书**

读取“待同步”文件，并将记录逐条添加到飞书多维表格。此步骤支持中断续传。

```bash
# 使用 prepare-feishu-sync 的默认输出作为输入
rocketlaunch-feishu execute-feishu-sync --to-sync-file "data/to_sync_launches/nextspaceflight.com_processed_to_sync.json"

# 自定义添加记录间的延迟（秒）
rocketlaunch-feishu execute-feishu-sync --to-sync-file records_to_add.json --delay-between-adds 0.5

# 启用在添加每条记录前的额外存在性检查 (更安全但更慢)
rocketlaunch-feishu execute-feishu-sync --to-sync-file records_to_add.json --pre-add-check
```
如果中途意外中断，再次运行相同的 `execute-feishu-sync` 命令可以从上次中断的地方继续。

### 一键执行完整同步流程

此命令按顺序执行 `fetch-data` -> `prepare-feishu-sync` -> `execute-feishu-sync`。推荐用于外部调度器（如 cron）。

```bash
# 运行完整流程，使用默认设置 (单页抓取，启用pre-add-check)
rocketlaunch-feishu run-daily-sync-flow

# 运行完整流程，抓取所有页面，并自定义其他参数
rocketlaunch-feishu run-daily-sync-flow --all-pages --max-pages-nsf 20 --execute-delay 0.3 --no-pre-add-check
```

### 其他辅助命令

**测试飞书多维表格记录列表功能:**

```bash
# 基本测试，使用 .env 中的默认表格和视图ID
rocketlaunch-feishu test-list-records

# 使用过滤器查询特定记录 (例如，发射日期时间等于 1743443160000)
rocketlaunch-feishu test-list-records --filter-json '{"conditions":[{"field_name":"发射日期时间","operator":"is","value":["ExactDate","1743443160000"]}],"conjunction":"and"}'

# 同时指定请求的字段和最大显示记录数
rocketlaunch-feishu test-list-records --fields-json "[\"发射任务名称\", \"Source\"]" --max-total-records 5
```

## 🐳 Docker 部署 (可选)

如果您希望通过 Docker 运行此应用 (例如，用于定时任务)：

1.  **创建 `.env.prod` 文件**:
    基于 `.env.example` 创建生产环境的配置文件，并填入真实的飞书凭证。
    ```bash
    cp .env.example .env.prod
    nano .env.prod
    ```

2.  **构建 Docker 镜像**:
    ```bash
    docker build -t rocketlaunch-feishu:latest .
    ```
    对于国内用户，如果遇到网络问题，可以尝试使用 `Dockerfile.local` (如果提供)：
    ```bash
    # docker build -t rocketlaunch-feishu:latest -f Dockerfile.local .
    ```

3.  **使用 Docker Compose (推荐)**:

(您需要一个 `docker-compose.yml` 文件来定义服务)
一个简单的 `docker-compose.yml` 示例，用于每日运行同步任务：
然后启动服务：
```bash
docker compose up -d
```
**注意**: 使用 Docker 进行定时任务的最佳实践通常是将 Docker 容器设计为执行一次任务然后退出，然后由宿主机的 cron 或 Kubernetes CronJob 等外部调度器来定时运行 `docker run your-image your-command` 或 `docker-compose run your-service your-command`。
在宿主机上设置 cron 任务


## 🧪 测试

运行单元测试 (如果配置了 `pytest`)：

```bash
pytest
# 或者指定特定测试文件
# pytest tests/test_html_parser_with_files.py
```

## 📁 项目结构

```
.
├── data/                     # 运行时生成的数据目录
│   ├── html/                 # 存储下载的 HTML 文件
│   ├── processed_launches/   # 存储 fetch-data 解析后的 JSON 数据
│   ├── to_sync_launches/     # 存储 prepare-feishu-sync 准备待同步的 JSON 数据
│   └── sync_progress.json    # (如果存在) execute-feishu-sync 的进度文件
├── logs/                     # 日志文件目录
├── src/
│   └── rocketlaunch_feishu/  # 主要应用代码
│       ├── __init__.py
│       ├── cli.py            # Typer 命令行接口
│       ├── html_parser.py    # HTML 解析逻辑
│       └── feishu_bitable.py # 飞书多维表格交互逻辑
├── tests/                    # 测试代码目录
├── .env.example              # 环境变量示例文件
├── .env                      # 本地开发环境变量 (不应提交到git)
├── Dockerfile                # Docker 镜像构建文件
├── pyproject.toml            # 项目元数据和依赖 (Poetry)
└── README.md                 # 本文档
```

## 📄 License

[MIT](LICENSE)
