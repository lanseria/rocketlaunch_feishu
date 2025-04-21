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
```

## 使用方法

手动触发数据同步：
```bash
cli sync-all
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