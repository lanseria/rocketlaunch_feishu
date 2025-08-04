FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

# 安装 tzdata 并设置时区
RUN apt-get update && apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制项目文件到容器中
COPY ./src ./src
COPY ./pyproject.toml ./
COPY ./README.md ./

# 升级 pip 并使用清华镜像
RUN pip install --upgrade

# 安装项目依赖（推荐使用 PEP 517/518 标准，支持 pyproject.toml）
RUN pip install -e .

ENTRYPOINT ["rocketlaunch-feishu", "start-scheduler"]