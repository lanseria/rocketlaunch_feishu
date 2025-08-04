# 使用官方 Python 镜像作为基础
FROM python:3.12-slim-bookworm

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

# --- 最终修正 ---
# 彻底更换 apt 源，解决 GPG 签名错误
# 1. 删除所有默认的源配置文件，包括 /etc/apt/sources.list 和 /etc/apt/sources.list.d/ 目录下的所有文件。
# 2. 创建一个全新的、干净的 sources.list 文件，指向一个可靠的镜像源（这里使用德国主镜像）。
# 3. 将所有 apt 操作合并在同一层，并进行清理，以优化镜像大小。
RUN rm -f /etc/apt/sources.list && \
    rm -rf /etc/apt/sources.list.d/* && \
    echo "deb http://ftp.de.debian.org/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb http://ftp.de.debian.org/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 优化 Docker 缓存：先复制并安装依赖
# 只有当 pyproject.toml 变化时，才会重新执行依赖安装
COPY ./pyproject.toml ./
COPY ./README.md ./

# 升级 pip 并安装项目依赖
RUN pip install --upgrade pip && \
    pip install -e .

# 最后复制源代码，这样修改代码不会触发依赖重装
COPY ./src ./src

# 设置容器启动命令
ENTRYPOINT ["rocketlaunch-feishu", "start-scheduler"]