import typer
from typing import Optional
from rich.console import Console
import os
import traceback
import httpx
import re
from .html_parser import parse_launches
import json
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
from .feishu_bitable import FeishuBitableHelper

app = typer.Typer()
console = Console()

def parse_datetime(obj):
    """解析发射日期和时间，返回 Unix 时间戳（UTC+8）"""
    date_str = obj.get('date', '')
    time_str = obj.get('time', '')
    if not date_str or not time_str:
        return None
    
    year = datetime.now().year
    date_match = re.match(r'([A-Z]{3,}) ?(\d{1,2})(?: (\d{4}))?', date_str)
    if not date_match:
        return None
        
    month_str, day_str, year_str = date_match.groups()
    month_map = {m: i for i, m in enumerate(['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'], 1)}
    month = month_map.get(month_str.upper())
    if not month:
        return None
        
    day = int(day_str)
    if year_str:
        year = int(year_str)
        
    try:
        # 先解析为 UTC 时间
        dt = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str}", "%Y-%m-%d %I:%M %p")
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        # 转换为 UTC+8
        dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return int(dt.timestamp())
    except Exception:
        return None

@app.command()
def hello(name: Optional[str] = typer.Argument(None)):
    """Simple greeting command"""
    if name:
        console.print(f"Hello [bold green]{name}[/bold green]!")
    else:
        console.print("Hello [bold blue]World[/bold blue]!")

@app.command()
def download_html():
    """从 rocketlaunch.live 下载最新发射数据"""
    url = "https://www.rocketlaunch.live/?pastOnly=1"
    output_dir = "data/html"
    output_file = f"{output_dir}/lastest.html"
    
    # 确保目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        console.print(f"正在从 {url} 下载数据...")
        response = httpx.get(url)
        response.raise_for_status()
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        
        console.print(f"[green]数据已保存到 {output_file}[/green]")
        return output_file
    except Exception as e:
        console.print(f"[red]下载失败: {str(e)}[/red]")
        raise typer.Exit(1)

@app.command()
def sync_launches():
    """下载、解析最新发射数据并同步到飞书多维表格"""
    try:
        # 1. 下载 HTML
        html_file = download_html()
        
        # 2. 解析 HTML 并添加时间戳
        with open(html_file, 'r', encoding='utf-8') as f:
            html_data = f.read()
        launches = parse_launches(html_data)
        console.print(f"[green]解析到 {len(launches)} 条发射数据[/green]")
        # 添加时间戳
        for launch in launches:
            timestamp = parse_datetime(launch)
            launch['timestamp'] = timestamp or 0
        
        # 保存原始数据
        timestamp = launches[-1].get('timestamp', 0)
        raw_dir = "data/raw"
        os.makedirs(raw_dir, exist_ok=True)
        output_path = f"{raw_dir}/lastest.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(launches, f, ensure_ascii=False, indent=2)
            
        console.print(f"[green]解析数据已保存到 {output_path}[/green]")
        filter_config = {
            "conditions": [
                {
                    "field_name": "发射日期时间",
                    "operator": "isGreater",  # greater than 大于
                    "value": ["ExactDate", str(timestamp * 1000)]  # 转换为毫秒级时间戳
                }
            ]
        }
        # 3. 获取多维表格数据进行对比
        helper = FeishuBitableHelper()
        records = helper.list_records(filter=filter_config)
        if not records:
            existing_timestamps = set()
        else:
            existing_timestamps = {int(record.__dict__['fields'].get('发射日期时间', 0)/1000) for record in records.items}
        console.log(f"[yellow]已有 {len(existing_timestamps)} 条记录[/yellow]")
        # 4. 同步新数据
        new_launches = [launch for launch in launches if launch['timestamp'] not in existing_timestamps]
        if not new_launches:
            console.print("[yellow]没有新的发射数据需要同步[/yellow]")
            return
            
        for launch in new_launches:
            console.print(f"[blue]同步数据: {launch}[/blue]")
            result = helper.add_launch_to_bitable(launch)
            if result:
                console.print(f"[green]已同步: {launch.get('mission', '')}[/green]")
            else:
                console.print(f"[red]同步失败: {launch.get('mission', '')}[/red]")
                
        console.print(f"[bold green]共同步 {len(new_launches)} 条新数据[/bold green]")
        
    except Exception as e:
        traceback.print_exc()
        console.print(f"[bold red]同步失败: {str(e)}[/bold red]")
        raise typer.Exit(1)

@app.command()
def sync_all():
    """完整的数据同步流程：下载、解析、同步数据"""
    sync_launches()

@app.command()
def schedule_daily(hour: int = typer.Option(18, help="每天执行的小时（24小时制）"), 
                  minute: int = typer.Option(0, help="每天执行的分钟")):
    """每天定时执行一次数据同步，默认每天 18:00 执行"""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        console.print("[bold red]无效的时间设置！小时应在0-23之间，分钟应在0-59之间[/bold red]")
        raise typer.Exit(1)
        
    console.print(f"[bold green]定时任务启动，每天 {hour:02d}:{minute:02d} 执行一次...[/bold green]")
    
    while True:
        now = datetime.now()
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if now >= next_run:
            # 已过今天执行时间，则定到明天
            next_run += timedelta(days=1)
            
        sleep_seconds = (next_run - now).total_seconds()
        console.print(f"距离下次执行还有 {int(sleep_seconds)} 秒，预计下次执行时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        
        time.sleep(sleep_seconds)
        
        try:
            console.print("[bold blue]开始执行定时同步任务...[/bold blue]")
            sync_launches()
            console.print("[bold green]定时任务执行完成[/bold green]")
        except Exception as e:
            console.print(f"[bold red]定时任务执行失败: {str(e)}[/bold red]")
            traceback.print_exc()

if __name__ == "__main__":
    app()
