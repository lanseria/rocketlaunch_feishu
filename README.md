# rocketlaunch_feishu

一个自动同步火箭发射数据到飞书多维表格的Docker应用。

## 功能特性

- 自动抓取 RocketLaunch.Live 网站的火箭发射数据
- 解析并存储发射数据到本地JSON文件
- 同步数据到飞书多维表格
- 支持增量更新，避免重复数据

## 安装部署

```bash
# 构建Docker镜像
cp .env.example .env.prod
docker build -t rocketlaunch_feishu:latest .
# 国内 
# docker build -t rocketlaunch_feishu:latest -f Dockerfile.local .
docker compose up -d
```

## 使用方法

手动触发数据同步：
```bash
rocketlaunch-feishu sync-all
rocketlaunch-feishu sync-launches --source "nextspaceflight.com"
```

Fetch data from a source:
```bash
rocketlaunch-feishu fetch-data --source "nextspaceflight.com" --all-pages
# This will create a file like data/processed_launches/nextspaceflight.com_processed_all_pages.json
```
Or specify an output file:
```bash
rocketlaunch-feishu fetch-data --source "rocketlaunch.live" --output-file my_rocket_data.json
```
Prepare data for Feishu sync (compare with Feishu):
```bash
rocketlaunch-feishu prepare-feishu-sync --processed-file "data/processed_launches/nextspaceflight.com_processed_all_pages.json"
# This will create a file like data/to_sync_launches/nextspaceflight.com_processed_all_pages_to_sync.json
```
Or specify an output file:
```bash
rocketlaunch-feishu prepare-feishu-sync --processed-file my_rocket_data.json --output-to-sync-file ready_for_feishu.json
```
Execute the sync to Feishu (with resume capability):
```bash
rocketlaunch-feishu execute-feishu-sync --to-sync-file "data/to_sync_launches/nextspaceflight.com_processed_all_pages_to_sync.json" --delay-between-adds 0.5
```

## 测试

```bash
python -m pytest tests/test_html_parser.py
python -m pytest tests/test_html_parser_with_files.py
```

## 项目结构

```
data/
  html/          # 存储下载的HTML文件
  raw/           # 存储解析后的JSON数据
src/
  __init__.py    
  cli.py         # CLI命令
  parser.py      # HTML解析器
  sync.py        # 数据同步逻辑
```

## License

MIT