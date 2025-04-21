import typer
from typing import Optional
from rich.console import Console
import os
import glob
import traceback
import httpx
import re
from .html_parser import parse_launches
import json
from datetime import datetime
from .feishu_bitable import FeishuBitableHelper
from datetime import datetime
from zoneinfo import ZoneInfo

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
def bitable_list():
    """从飞书 Bitable 中读取数据，并以表格方式打印"""
    console.print("初始化 FeishuBitableHelper ...")
    try:
        helper = FeishuBitableHelper()
        # helper.list_table_fields()
        # helper.list_records(field_names=["发射日期时间", "发射任务名称", "Rocket Model", "发射位", "发射地点"], 
        #     sort=[{"field_name": "发射日期时间", "desc": True}]
        # )
        launch = {
            "mission": "Starlink-173 (8-8)",
            "vehicle": "Falcon 9",
            "pad": "SLC-4E",
            "location": "California United States SLC-4E, Vandenberg SFB ,",
            "timestamp": 1717851480
        }
        helper.add_launch_to_bitable(launch)
    except Exception as e:
        console.print(f"[bold red]获取多维表格应用失败: {e}[/bold red]")

@app.command()
def bitable_import_after(timestamp: int = typer.Argument(..., help="只导入大于此时间戳的数据")):
    """
    查询 data/json/ 目录下最新的 json 文件，将发射时间(timestamp)大于指定值的数据批量插入飞书多维表格
    """
    console.print("初始化 FeishuBitableHelper ...")
    try:
        helper = FeishuBitableHelper()
        # 查找最新的 json 文件
        json_files = glob.glob('data/json/*.json')
        if not json_files:
            console.print('[red]未找到任何 JSON 文件[/red]')
            raise typer.Exit(1)
        latest_file = max(json_files, key=os.path.getmtime)
        with open(latest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 过滤出 timestamp 大于指定值的
        filtered = [item for item in data if isinstance(item, dict) and item.get("timestamp", 0) > timestamp]
        if not filtered:
            console.print(f"[yellow]没有找到 timestamp 大于 {timestamp} 的数据[/yellow]")
            return
        # 插入到多维表格
        for launch in filtered:
            result = helper.add_launch_to_bitable(launch)
            if result:
                console.print(f"[green]已插入: {launch.get('mission', '')}[/green]")
            else:
                console.print(f"[red]插入失败: {launch.get('mission', '')}[/red]")
        console.print(f"[bold green]共插入 {len(filtered)} 条数据[/bold green]")
    except Exception as e:
        console.print(f"[bold red]导入失败: {e}[/bold red]")

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

if __name__ == "__main__":
    app()
