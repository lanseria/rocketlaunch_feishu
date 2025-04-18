import typer
from typing import Optional
from rich.console import Console
from rich.table import Table
import os
import glob
from .html_parser import parse_launches
import json
from datetime import datetime
from .feishu_bitable import FeishuBitableHelper

app = typer.Typer()
console = Console()

@app.command()
def hello(name: Optional[str] = typer.Argument(None)):
    """Simple greeting command"""
    if name:
        console.print(f"Hello [bold green]{name}[/bold green]!")
    else:
        console.print("Hello [bold blue]World[/bold blue]!")

@app.command()
def parse_html(file: str = typer.Argument(..., help="HTML文件路径")):
    """解析指定HTML文件中的发射数据"""
    if not os.path.isfile(file):
        console.print(f"[red]文件不存在: {file}[/red]")
        raise typer.Exit(1)
    with open(file, 'r', encoding='utf-8') as f:
        html_data = f.read()
    launches = parse_launches(html_data)
    # 保存到 data/raw_{timestamp}.json
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = f"data/raw_json/raw_{timestamp}.json"
    with open(output_path, 'w', encoding='utf-8') as out_f:
        json.dump(launches, out_f, ensure_ascii=False, indent=2)
    console.print(f"[green]解析结果已保存到 {output_path}[/green]")
    for launch in launches:
        console.print(launch)

@app.command()
def read_latest_json():
    """读取 data/raw_json/ 目录下最新的 json 文件，并以表格方式打印，并为每个对象添加时间戳字段 timestamp"""
    import re
    import time
    json_files = glob.glob('data/raw_json/raw_*.json')
    if not json_files:
        console.print('[red]未找到任何 JSON 文件[/red]')
        raise typer.Exit(1)
    latest_file = max(json_files, key=os.path.getmtime)
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not data:
        console.print(f'[yellow]文件 {latest_file} 为空[/yellow]')
        return
    # 处理每个对象，添加 timestamp 字段
    def parse_datetime(obj):
        # 允许 date 可能带年份或不带年份
        date_str = obj.get('date', '')
        time_str = obj.get('time', '')
        if not date_str or not time_str:
            return None
        # 处理 date_str 可能带年份
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
        # 处理 time_str
        try:
            dt = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str}", "%Y-%m-%d %I:%M %p")
            return int(time.mktime(dt.timetuple()))
        except Exception:
            return None
    # 添加 timestamp 字段
    for obj in data:
        obj['timestamp'] = parse_datetime(obj) or 0
    # 保存带 timestamp 的数据到 data/json/{timestamp}.json
    output_dir = 'data/json'
    os.makedirs(output_dir, exist_ok=True)
    save_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = f'{output_dir}/{save_timestamp}.json'
    with open(output_path, 'w', encoding='utf-8') as out_f:
        json.dump(data, out_f, ensure_ascii=False, indent=2)
    console.print(f'[green]已保存带 timestamp 字段的数据到 {output_path}[/green]')
    # 假设每个 launch 是 dict，取第一个 launch 的 key 作为表头
    first = data[0]
    table = Table(title=f"{latest_file} 内容预览")
    for key in first.keys():
        table.add_column(str(key))
    for launch in data:
        row = [str(launch.get(k, '')) for k in first.keys()]
        table.add_row(*row)
    console.print(table)

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
if __name__ == "__main__":
    app()
