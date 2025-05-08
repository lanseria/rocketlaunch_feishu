import typer
from typing import Optional, List
import os
import traceback
import httpx
import re
from .html_parser import parse_launches_rocketlaunchlive, parse_launches_nextspaceflight
import json
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo # Using ZoneInfo
from .feishu_bitable import FeishuBitableHelper
import logging
from logging.handlers import RotatingFileHandler
from enum import Enum
from bs4 import BeautifulSoup # For checking "No more results"

# Configure logging
def setup_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    logger_instance = logging.getLogger("rocketlaunch_feishu") # Use a specific name for your app's logger
    logger_instance.setLevel(logging.INFO)
    
    # Prevent duplicate handlers if called multiple times (e.g. in tests or reloads)
    if logger_instance.hasHandlers():
        logger_instance.handlers.clear()

    file_handler = RotatingFileHandler(
        f"{log_dir}/launch_sync.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(levelname)s: %(message)s' # Simpler for console
    ))
    
    logger_instance.addHandler(file_handler)
    logger_instance.addHandler(console_handler)

    # Configure lark_oapi logger to be less verbose by default, or match your app's level
    lark_logger = logging.getLogger("lark_oapi")
    lark_logger.setLevel(logging.WARNING) # Or logging.INFO if you need more lark details
    lark_logger.addHandler(file_handler) # Optionally send lark logs to your file too
    lark_logger.addHandler(console_handler) # And console
    
    return logger_instance

logger = setup_logging()

app = typer.Typer()

class LaunchSource(str, Enum):
    ROCKETLAUNCH_LIVE = "rocketlaunch.live"
    NEXTSPACEFLIGHT = "nextspaceflight.com"

def parse_datetime_rocketlaunchlive_dict(obj: dict) -> Optional[int]:
    """
    解析来自 rocketlaunch.live 的发射日期和时间字典，返回 Unix 时间戳（UTC+8）。
    原有的 parse_datetime 函数，重命名以区分。
    Assumes the time string (e.g., "02:47 AM EDT") should be interpreted as UTC if no explicit timezone parsing is done.
    This function's original assumption about input time being UTC might need review if rocketlaunch.live provides varied timezones.
    """
    date_str = obj.get('date', '')
    time_str = obj.get('time', '') # e.g., "02:47 AM EDT" or "10:00 PM UTC" or "10:00 PM"
    
    if not date_str or not time_str:
        return None
    
    current_year = datetime.now().year
    date_match = re.match(r'([A-Z]{3,}) ?(\d{1,2})(?: (\d{4}))?', date_str) # Example: "SEPTEMBER 18 2023" or "SEP 18"
    if not date_match:
        logger.warning(f"RL.live Date parsing failed for: {date_str}")
        return None
        
    month_str, day_str, year_str = date_match.groups()
    month_map = {m: i for i, m in enumerate(['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'], 1)}
    month = month_map.get(month_str.upper()[:3]) # Use first 3 chars for month
    if not month:
        logger.warning(f"RL.live Month parsing failed for: {month_str}")
        return None
        
    day = int(day_str)
    year = int(year_str) if year_str else current_year
        
    try:
        # Attempt to parse time like "HH:MM AM/PM" possibly with timezone suffix
        time_parts = time_str.split(" ")
        time_val = time_parts[0] # HH:MM
        am_pm = ""
        if len(time_parts) > 1 and (time_parts[1].upper() == "AM" or time_parts[1].upper() == "PM"):
            am_pm = time_parts[1].upper()
            # TODO: More robustly handle timezones like EDT, PST, UTC if present in time_parts[2:]
            # For now, sticking to original logic: assume time is UTC.
        
        # Construct datetime string for strptime
        datetime_input_str = f"{year}-{month:02d}-{day:02d} {time_val} {am_pm}".strip()
        dt_format = "%Y-%m-%d %I:%M %p" if am_pm else "%Y-%m-%d %H:%M" # Handle 24h if no AM/PM

        dt = datetime.strptime(datetime_input_str, dt_format)
        
        # Original logic: treat parsed time as UTC, then convert to Asia/Shanghai
        # This is only correct if rocketlaunch.live provides times in UTC or the scraper gets UTC times.
        # If times are local (e.g. EDT, PDT), this needs a more sophisticated timezone handling.
        dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_cst = dt_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        return int(dt_cst.timestamp())
    except Exception as e:
        logger.warning(f"RL.live Datetime parsing failed for '{date_str} {time_str}': {e}")
        return None

def download_html_from_url(url: str, source_name: str) -> str:
    """从指定URL下载HTML数据 / Download HTML data from a given URL"""
    output_dir = "data/html"
    # Sanitize source_name for filename
    safe_source_name = "".join(c if c.isalnum() else "_" for c in source_name)
    output_file = f"{output_dir}/{safe_source_name}_latest.html"
    
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        logger.info(f"Downloading data from {url} for source {source_name} / 正在从 {url} ({source_name}) 下载数据...")
        # Add a user-agent, some sites might block default httpx/python user-agent
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        with httpx.Client(timeout=30.0, follow_redirects=True) as client: # Increased timeout
            response = client.get(url, headers=headers)
            response.raise_for_status() # Raise an exception for HTTP 4xx/5xx errors
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        
        logger.info(f"Data saved to {output_file} / 数据已保存到 {output_file}")
        return output_file
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error during download from {url}: {e.response.status_code} - {e.response.text[:200]} / 下载HTTP错误: {e.response.status_code}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        logger.error(f"Request error during download from {url}: {str(e)} / 下载请求错误: {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        logger.error(f"Download failed for {url}: {str(e)} / 下载失败: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)

def download_html_for_source(
    source: LaunchSource, 
    all_pages: bool = False,
    max_pages_nextspaceflight: int = 50 # Safety limit for nextspaceflight all_pages
) -> str:
    """
    Downloads HTML data for a given source.
    Handles single page download or multi-page download and concatenation for nextspaceflight.com.
    Returns the path to the (potentially combined) HTML file.
    """
    output_dir = "data/html"
    os.makedirs(output_dir, exist_ok=True)
    safe_source_name = "".join(c if c.isalnum() else "_" for c in source.value)
    # Filename will indicate if it's all pages for clarity
    all_pages_suffix = "_all_pages" if all_pages and source == LaunchSource.NEXTSPACEFLIGHT else ""
    output_file = f"{output_dir}/{safe_source_name}_latest{all_pages_suffix}.html"

    combined_html_content = ""
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            if source == LaunchSource.ROCKETLAUNCH_LIVE:
                url = "https://www.rocketlaunch.live/?pastOnly=1"
                logger.info(f"Downloading data from {url} for source {source.value}...")
                response = client.get(url, headers=headers)
                response.raise_for_status()
                combined_html_content = response.text
            
            elif source == LaunchSource.NEXTSPACEFLIGHT:
                base_url = "https://nextspaceflight.com/launches/past/"
                if not all_pages:
                    logger.info(f"Downloading data from {base_url} (page 1) for source {source.value}...")
                    response = client.get(base_url, headers=headers)
                    response.raise_for_status()
                    combined_html_content = response.text
                else:
                    logger.info(f"Downloading all pages from {base_url} for source {source.value}...")
                    # We need to extract the main launch container part from each page
                    # and append them. The full HTML structure might not merge well.
                    # A simpler approach for now: just get the content of the main div.
                    # A more robust way would be to parse each page, extract launch divs,
                    # and then create a new minimal HTML with all launch divs.
                    # For now, let's try concatenating the content of <div class="mdl-grid">
                    
                    all_launch_cards_html = [] # Store HTML strings of individual launch cards
                    
                    for page_num in range(1, max_pages_nextspaceflight + 1):
                        page_url = f"{base_url}?page={page_num}&search=" # Assuming search is empty
                        logger.info(f"Downloading page {page_num}: {page_url}")
                        
                        # Add a small delay to be polite to the server
                        if page_num > 1:
                            time.sleep(1) 

                        response = client.get(page_url, headers=headers)
                        response.raise_for_status()
                        page_content = response.text
                        
                        soup = BeautifulSoup(page_content, 'html.parser')
                        
                        # Check for "No more results!" or similar indicator
                        no_more_results_indicator = soup.find(text=re.compile(r"No more results!", re.IGNORECASE))
                        if no_more_results_indicator:
                            logger.info(f"No more results found at page {page_num}. Stopping.")
                            break
                        
                        # Find the main grid containing launch cards
                        main_grid = soup.find('div', class_='mdl-grid', style=re.compile(r"justify-content: center"))
                        if not main_grid:
                            logger.warning(f"Could not find main launch grid on page {page_num}. Content might be partial.")
                            # Decide if to add the whole page_content or skip
                            # For now, if grid not found, we might have issues.
                            # Let's try to find individual cards as a fallback.
                            
                        # Extract individual launch cards
                        # launch_cards_on_page = soup.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split())
                        # Prefer to get them from within the main_grid if found
                        target_container = main_grid if main_grid else soup
                        launch_cards_on_page = target_container.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split())
                        
                        if not launch_cards_on_page and not no_more_results_indicator:
                            # This might mean an empty page before "No more results" or a layout change
                            logger.info(f"No launch cards found on page {page_num}, but no 'No more results' indicator. Assuming end of data or issue.")
                            break


                        for card_div in launch_cards_on_page:
                            all_launch_cards_html.append(str(card_div))

                        if page_num == max_pages_nextspaceflight:
                            logger.warning(f"Reached max_pages limit ({max_pages_nextspaceflight}) for NextSpaceflight.")
                    
                    # Construct a minimal HTML structure to hold all launch cards
                    if all_launch_cards_html:
                        combined_html_content = f"<html><body><div class='mdl-grid'>{''.join(all_launch_cards_html)}</div></body></html>"
                    else:
                        logger.info("No launch cards collected from NextSpaceflight multi-page scrape.")
                        combined_html_content = "<html><body></body></html>" # Empty valid HTML
            else:
                logger.error(f"Unknown source for download: {source.value}")
                raise typer.Exit(1)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(combined_html_content)
        
        logger.info(f"Data saved to {output_file} / 数据已保存到 {output_file}")
        return output_file

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error during download for {source.value}: {e.response.status_code} - {e.response.text[:200]}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        logger.error(f"Request error during download for {source.value}: {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        logger.error(f"Download failed for {source.value}: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)

@app.command()
def sync_launches(
    source: LaunchSource = typer.Option(
        LaunchSource.ROCKETLAUNCH_LIVE, 
        help="The data source to sync from.",
        case_sensitive=False
    ),
    all_pages: bool = typer.Option(
        False, 
        "--all-pages/--single-page", # Makes it a toggle, default False (single page)
        help="For NextSpaceflight: fetch all pages of past launches. Ignored for other sources."
    ),
    max_pages_nextspaceflight: int = typer.Option(
        50,
        help="Safety limit for 'all_pages' mode with NextSpaceflight."
    )
):
    """下载、解析最新发射数据并同步到飞书多维表格"""
    try:
        # 1. Download HTML (potentially multiple pages for nextspaceflight)
        html_file = download_html_for_source(source, all_pages, max_pages_nextspaceflight)
        
        with open(html_file, 'r', encoding='utf-8') as f:
            html_data = f.read()
        
        if not html_data.strip():
            logger.warning(f"Downloaded HTML file {html_file} is empty. Skipping parsing and sync.")
            return

        processed_launches: List[dict] = []

        if source == LaunchSource.ROCKETLAUNCH_LIVE:
            if all_pages:
                logger.info("--all-pages is ignored for rocketlaunch.live source.")
            raw_parsed_launches = parse_launches_rocketlaunchlive(html_data)
            # ... (rest of rocketlaunch.live processing remains the same as before) ...
            for launch_data in raw_parsed_launches:
                timestamp = parse_datetime_rocketlaunchlive_dict(launch_data)
                pad_val = launch_data.get('pad', '')
                loc_val = launch_data.get('location', '')
                pad_location_combined = f"{pad_val}, {loc_val}".strip().strip(',')
                if not pad_location_combined or pad_location_combined == ",":
                    pad_location_combined = "Unknown"
                
                processed_launches.append({
                    'mission': launch_data.get('mission'),
                    'vehicle': launch_data.get('vehicle'),
                    'pad_location': pad_location_combined,
                    'timestamp': timestamp or 0,
                    'status': "Unknown", 
                    'mission_description': "N/A", 
                    'source_name': source.value
                })

        elif source == LaunchSource.NEXTSPACEFLIGHT:
            processed_launches = parse_launches_nextspaceflight(html_data, source.value)
        
        logger.info(f"Parsed {len(processed_launches)} launch records from {source.value} / 从 {source.value} 解析到 {len(processed_launches)} 条发射数据")

        if not processed_launches:
            logger.info("No launch data parsed, exiting. / 没有解析到发射数据，退出。")
            return

        # Save processed (enriched) data
        safe_source_name = "".join(c if c.isalnum() else "_" for c in source.value)
        all_pages_suffix_json = "_all_pages" if all_pages and source == LaunchSource.NEXTSPACEFLIGHT else ""
        raw_dir = "data/raw"
        os.makedirs(raw_dir, exist_ok=True)
        output_path = f"{raw_dir}/{safe_source_name}_latest_processed{all_pages_suffix_json}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(processed_launches, f, ensure_ascii=False, indent=2)
        logger.info(f"Processed data saved to {output_path} / 处理后数据已保存到 {output_path}")

        valid_launches_for_sync = [
            l for l in processed_launches 
            if l.get('timestamp', 0) > 0 or l.get('status') in ["Scheduled", "TBD"]
        ]
        if not valid_launches_for_sync:
            logger.info("No launches with valid timestamps (or valid TBD/Scheduled status) to process for Feishu sync.")
            return
        
        actual_timestamps = [l['timestamp'] for l in valid_launches_for_sync if l['timestamp'] > 0]
        
        # If --all-pages is used, we might be fetching very old data.
        # The filter for Feishu records needs careful consideration.
        # Option 1: Fetch ALL records from Feishu for this source and do a full local diff. (memory intensive for large Feishu tables)
        # Option 2: If oldest_timestamp_in_scrape is very old, don't filter by time, only by source.
        # Option 3: Still use oldest_timestamp_in_scrape. (Chosen here for consistency, but be aware)
        
        oldest_timestamp_in_scrape = min(actual_timestamps) if actual_timestamps else 0

        filter_for_feishu = {"conditions": [], "conjunction": "and"}
        
        # Always filter by source
        filter_for_feishu["conditions"].append({
            "field_name": "Source",
            "operator": "is",
            "value": [source.value]
        })

        # Add time filter if oldest_timestamp_in_scrape is valid AND we are NOT in all_pages mode
        # OR if we are in all_pages mode but want to limit feishu query (can lead to missing updates for older records if feishu is not complete)
        # For full sync with --all-pages, it might be better to NOT filter by date and get all records for that source.
        # However, this could be a very large query.
        # Current strategy: if all_pages, we still use the oldest timestamp from the scrape to limit Feishu query.
        # This assumes we are trying to fill in missing data from that point onwards.
        # If the goal of --all-pages is to *refresh* all data, the Feishu interaction would need to be more complex (e.g., update existing).
        if oldest_timestamp_in_scrape > 0: 
            filter_for_feishu["conditions"].append({
                "field_name": "发射日期时间", 
                "operator": "isGreaterOrEqual", 
                "value": ["ExactDate", str(oldest_timestamp_in_scrape * 1000)] 
            })
        
        helper = FeishuBitableHelper()
        # Adding '发射状态' to fields_to_fetch if we want to update based on status change (not implemented here)
        fields_to_fetch = ["发射日期时间", "Source", "发射任务名称"]
        bitable_records_response = helper.list_records(filter=filter_for_feishu, field_names=json.dumps(fields_to_fetch), page_size=500) # Increased page_size for list_records
        
        existing_records_tuples = set()
        if bitable_records_response and bitable_records_response.items:
            for record in bitable_records_response.items:
                ts_millis = record.fields.get("发射日期时间") 
                rec_source_field = record.fields.get("Source") 
                rec_mission = record.fields.get("发射任务名称", "")

                rec_source_val = "Unknown"
                if isinstance(rec_source_field, str): rec_source_val = rec_source_field
                elif isinstance(rec_source_field, list) and rec_source_field: rec_source_val = rec_source_field[0]

                existing_records_tuples.add(
                    (int(ts_millis / 1000) if ts_millis else 0, 
                     rec_source_val, 
                     rec_mission.strip().lower())
                )
            logger.info(f"Found {len(existing_records_tuples)} existing records in Feishu matching criteria (Source: {source.value}, Time >= {oldest_timestamp_in_scrape if oldest_timestamp_in_scrape > 0 else 'Any'}).")
        else:
            logger.info(f"No existing records found in Feishu matching criteria or failed to fetch (Source: {source.value}, Time >= {oldest_timestamp_in_scrape if oldest_timestamp_in_scrape > 0 else 'Any'}).")
            
        new_launches_to_add = []
        for launch in valid_launches_for_sync:
            current_launch_tuple = (
                launch['timestamp'], 
                launch['source_name'],
                launch.get('mission', "").strip().lower()
            )
            if current_launch_tuple not in existing_records_tuples:
                new_launches_to_add.append(launch)
        
        if not new_launches_to_add:
            logger.info("No new launch data to sync to Feishu based on (Timestamp, Source, Mission) comparison.")
            return
        
        new_launches_to_add.sort(key=lambda x: x['timestamp'] if x['timestamp'] > 0 else float('inf'))

        added_count = 0
        for launch_to_add in new_launches_to_add:
            # logger.info(f"Syncing to Feishu: {launch_to_add.get('mission', '')} (Source: {launch_to_add.get('source_name')}, Status: {launch_to_add.get('status')})")
            result = helper.add_launch_to_bitable(launch_to_add) # add_launch_to_bitable handles its own logging for success/failure
            if result:
                added_count +=1
        
        logger.info(f"Attempted to sync {len(new_launches_to_add)} new records. Successfully synced {added_count} records to Feishu for source {source.value}.")
        
    except Exception as e:
        logger.error(f"Sync process failed for source {source.value}: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1) # Exit for this specific sync, but sync_all can continue

@app.command()
def sync_all(
    all_pages_nextspaceflight: bool = typer.Option(
        False, 
        "--all-pages-nsf/--single-page-nsf",
        help="For NextSpaceflight source during sync_all: fetch all pages. Default is single page."
    ),
    max_pages_nextspaceflight: int = typer.Option(
        50,
        help="Safety limit for 'all_pages' mode with NextSpaceflight during sync_all."
    )
):
    """
    完整的数据同步流程：针对所有已配置的源执行下载、解析、同步数据。
    """
    logger.info("Starting sync for all configured sources.")
    for source_enum_member in LaunchSource:
        logger.info(f"--- Syncing for source: {source_enum_member.value} ---")
        try:
            current_all_pages = False
            if source_enum_member == LaunchSource.NEXTSPACEFLIGHT:
                current_all_pages = all_pages_nextspaceflight
            
            sync_launches(
                source=source_enum_member, 
                all_pages=current_all_pages, 
                max_pages_nextspaceflight=max_pages_nextspaceflight
            )
            logger.info(f"--- Finished syncing for source: {source_enum_member.value} ---")
        except typer.Exit:
            logger.error(f"--- Sync for source {source_enum_member.value} exited. Continuing with next source if any. ---")
        except Exception as e:
            logger.error(f"--- Unhandled error during sync for source {source_enum_member.value}: {e} ---")
            logger.error(traceback.format_exc())
    logger.info("Finished sync for all sources.")

@app.command()
def schedule_daily(
    hour: int = typer.Option(18, help="每天执行的小时（24小时制）"), 
    minute: int = typer.Option(0, help="每天执行的分钟"),
    source_to_schedule: Optional[LaunchSource] = typer.Option(
        None, 
        "--source",
        help="Specific source to schedule. If None, schedules 'sync_all'.",
        case_sensitive=False
    ),
    all_pages_nsf_scheduled: bool = typer.Option(
        False,
        "--all-pages-nsf-scheduled/--single-page-nsf-scheduled",
        help="For NextSpaceflight source during scheduled task: fetch all pages. Default is single page."
    ),
    max_pages_nsf_scheduled: int = typer.Option(
        50,
        help="Safety limit for 'all_pages' mode with NextSpaceflight during scheduled task."
    )
):
    """每天定时执行一次数据同步"""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        logger.error("Invalid time settings! Hour must be 0-23, minute must be 0-59")
        raise typer.Exit(1)
    
    action_description = ""
    if source_to_schedule:
        action_description = f"sync_launches for {source_to_schedule.value}"
        if source_to_schedule == LaunchSource.NEXTSPACEFLIGHT:
            action_description += " (all_pages)" if all_pages_nsf_scheduled else " (single_page)"
    else:
        action_description = f"sync_all (NextSpaceflight: {'all_pages' if all_pages_nsf_scheduled else 'single_page'})"

    logger.info(f"Starting scheduled job for '{action_description}', will run daily at {hour:02d}:{minute:02d}")
    
    while True:
        now = datetime.now()
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if now >= next_run:
            next_run += timedelta(days=1)
            
        sleep_seconds = (next_run - now).total_seconds()
        logger.info(f"Next run for '{action_description}' in {int(sleep_seconds // 3600)}h {int((sleep_seconds % 3600) // 60)}m {int(sleep_seconds % 60)}s, at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        
        time.sleep(max(1, sleep_seconds))
        
        try:
            logger.info(f"Starting scheduled task: {action_description}...")
            if source_to_schedule:
                current_all_pages_for_source = False
                if source_to_schedule == LaunchSource.NEXTSPACEFLIGHT:
                    current_all_pages_for_source = all_pages_nsf_scheduled
                sync_launches(
                    source=source_to_schedule, 
                    all_pages=current_all_pages_for_source, 
                    max_pages_nextspaceflight=max_pages_nsf_scheduled
                )
            else:
                sync_all(
                    all_pages_nextspaceflight=all_pages_nsf_scheduled, 
                    max_pages_nextspaceflight=max_pages_nsf_scheduled
                )
            logger.info(f"Scheduled task ({action_description}) completed successfully.")
        except Exception as e:
            logger.error(f"Scheduled task ({action_description}) failed: {str(e)}")
            logger.error(traceback.format_exc())

@app.command()
def hello(name: Optional[str] = typer.Argument(None)):
    """Simple greeting command"""
    if name:
        logger.info(f"Hello {name}! / 你好 {name}!")
    else:
        logger.info("Hello World! / 你好 世界!")


if __name__ == "__main__":
    app()