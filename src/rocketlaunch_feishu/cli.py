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
from bs4 import BeautifulSoup 
import hashlib # For generating hash of data file

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


# --- CONFIGURABLE FILE PATHS ---
PROCESSED_DATA_DIR = "data/processed_launches"
TO_SYNC_DATA_DIR = "data/to_sync_launches"
SYNC_PROGRESS_FILE = "data/sync_progress.json"
# Ensure these directories exist
os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
os.makedirs(TO_SYNC_DATA_DIR, exist_ok=True)
os.makedirs("data/html", exist_ok=True) # From download_html_for_source
os.makedirs("data/raw", exist_ok=True)  # From download_html_for_source or fetch_data

# download_html_for_source (from previous version) - ensure it saves to data/html
# (Minor change: it's mostly a helper now, main logic in fetch_data)
def download_html_for_source(
    source: LaunchSource, 
    all_pages: bool = False,
    max_pages_nextspaceflight: int = 236 
) -> str:
    # ... (implementation from previous answer, ensuring it saves to data/html/{source}_latest.html) ...
    # This function now just downloads and returns the path to the raw HTML file(s).
    # The concatenation logic for nextspaceflight multi-page should ideally be here or called by fetch_data.
    # For simplicity, let's assume it returns one path, which might be a combined HTML file.
    output_dir = "data/html"
    os.makedirs(output_dir, exist_ok=True)
    safe_source_name = "".join(c if c.isalnum() else "_" for c in source.value)
    all_pages_suffix = "_all_pages" if all_pages and source == LaunchSource.NEXTSPACEFLIGHT else ""
    # This output_file is for the raw HTML from download step
    raw_html_output_file = f"{output_dir}/{safe_source_name}_latest_downloaded{all_pages_suffix}.html"

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
                    # ... (Multi-page download logic from previous answer) ...
                    # This part should fill combined_html_content
                    logger.info(f"Downloading all pages from {base_url} for source {source.value}...")
                    all_launch_cards_html = []
                    for page_num in range(1, max_pages_nextspaceflight + 1):
                        page_url = f"{base_url}?page={page_num}&search="
                        logger.info(f"Downloading page {page_num}: {page_url}")
                        if page_num > 1: time.sleep(1)
                        response = client.get(page_url, headers=headers)
                        response.raise_for_status()
                        page_content = response.text
                        soup = BeautifulSoup(page_content, 'html.parser')
                        if soup.find(text=re.compile(r"No more results!", re.IGNORECASE)):
                            logger.info(f"No more results found at page {page_num}. Stopping.")
                            break
                        main_grid = soup.find('div', class_='mdl-grid', style=re.compile(r"justify-content: center"))
                        target_container = main_grid if main_grid else soup
                        launch_cards_on_page = target_container.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split())
                        if not launch_cards_on_page and not soup.find(text=re.compile(r"No more results!", re.IGNORECASE)):
                            logger.info(f"No launch cards found on page {page_num}, assuming end of data.")
                            break
                        for card_div in launch_cards_on_page:
                            all_launch_cards_html.append(str(card_div))
                        if page_num == max_pages_nextspaceflight:
                            logger.warning(f"Reached max_pages limit ({max_pages_nextspaceflight}) for NextSpaceflight.")
                    if all_launch_cards_html:
                        combined_html_content = f"<html><body><div class='mdl-grid'>{''.join(all_launch_cards_html)}</div></body></html>"
                    else:
                        combined_html_content = "<html><body></body></html>"
            else: # Should not happen with Enum
                raise typer.Exit(1)

        with open(raw_html_output_file, "w", encoding="utf-8") as f:
            f.write(combined_html_content)
        logger.info(f"Raw HTML data saved to {raw_html_output_file}")
        return raw_html_output_file
    except Exception as e: # Broad exception for download issues
        logger.error(f"Download failed for {source.value}: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(code=1)

def generate_file_hash(filepath):
    """Generates a SHA256 hash for a file."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        buf = f.read(65536)  # Read in 64k chunks
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()

@app.command()
def fetch_data(
    source: LaunchSource = typer.Option(..., help="The data source to fetch from."), # Made source mandatory
    all_pages: bool = typer.Option(False, "--all-pages/--single-page", help="For NextSpaceflight: fetch all pages."),
    max_pages_nextspaceflight: int = typer.Option(236, help="Safety limit for 'all_pages' with NextSpaceflight."),
    output_file: Optional[str] = typer.Option(None, help="Override default output JSON file path for processed data.")
):
    """Downloads HTML from the source, parses it, and saves the structured launch data to a JSON file."""
    try:
        logger.info(f"Starting data fetching for source: {source.value}")
        # 1. Download HTML
        # The download_html_for_source now handles single/multi-page and saves the raw HTML.
        raw_html_file = download_html_for_source(source, all_pages, max_pages_nextspaceflight)

        if not os.path.exists(raw_html_file) or os.path.getsize(raw_html_file) == 0:
            logger.error(f"Downloaded HTML file {raw_html_file} is empty or not found. Aborting fetch.")
            raise typer.Exit(1)

        with open(raw_html_file, 'r', encoding='utf-8') as f:
            html_data = f.read()

        # 2. Parse HTML
        processed_launches: List[dict] = []
        if source == LaunchSource.ROCKETLAUNCH_LIVE:
            raw_parsed_launches = parse_launches_rocketlaunchlive(html_data)
            for launch_data in raw_parsed_launches:
                timestamp = parse_datetime_rocketlaunchlive_dict(launch_data)
                pad_val = launch_data.get('pad', '')
                loc_val = launch_data.get('location', '')
                pad_location_combined = f"{pad_val}, {loc_val}".strip().strip(',')
                if not pad_location_combined or pad_location_combined == ",": pad_location_combined = "Unknown"
                processed_launches.append({
                    'mission': launch_data.get('mission'), 'vehicle': launch_data.get('vehicle'),
                    'pad_location': pad_location_combined, 'timestamp': timestamp or 0,
                    'status': "Unknown", 'mission_description': "N/A", 'source_name': source.value
                })
        elif source == LaunchSource.NEXTSPACEFLIGHT:
            processed_launches = parse_launches_nextspaceflight(html_data, source.value)
        
        logger.info(f"Parsed {len(processed_launches)} launch records from {source.value}")

        if not processed_launches:
            logger.info("No launch data parsed. Output file will be empty or not created if default.")
            # Still create an empty JSON if an output file is specified, or a default one.
        
        # 3. Save processed data to a JSON file
        if output_file is None:
            safe_source_name = "".join(c if c.isalnum() else "_" for c in source.value)
            all_pages_suffix = "_all_pages" if all_pages and source == LaunchSource.NEXTSPACEFLIGHT else ""
            # This is the output of the fetch_data command, the processed launches.
            output_file = f"{PROCESSED_DATA_DIR}/{safe_source_name}_processed{all_pages_suffix}.json"
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True) # Ensure dir exists if custom path
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(processed_launches, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully fetched and processed data. Saved to: {output_file}")
        logger.info(f"This file can now be used with 'prepare-feishu-sync' and 'execute-feishu-sync'.")

    except Exception as e:
        logger.error(f"Data fetching process failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)

@app.command()
def prepare_feishu_sync(
    processed_file: str = typer.Option(..., help="Path to the JSON file containing processed launch data (from fetch-data)."),
    output_to_sync_file: Optional[str] = typer.Option(None, help="Override default output JSON file path for 'to-sync' data.")
):
    """Compares processed launch data with Feishu and prepares a list of records to be synced."""
    try:
        if not os.path.exists(processed_file):
            logger.error(f"Processed data file not found: {processed_file}")
            raise typer.Exit(1)

        with open(processed_file, 'r', encoding='utf-8') as f:
            processed_launches = json.load(f)

        if not processed_launches:
            logger.info(f"No launches in {processed_file} to prepare for sync. Exiting.")
            if output_to_sync_file:
                # Ensure directory exists before writing empty file
                os.makedirs(os.path.dirname(output_to_sync_file), exist_ok=True)
                with open(output_to_sync_file, 'w', encoding='utf-8') as f_empty:
                    json.dump([], f_empty)
            return

        source_value_from_file = processed_launches[0].get('source_name')
        if not source_value_from_file:
            logger.error("Could not determine source from processed file. 'source_name' missing in records.")
            raise typer.Exit(1)
        
        logger.info(f"Preparing Feishu sync for data from file: {processed_file} (Source: {source_value_from_file})")

        # --- MODIFIED LOGIC HERE ---
        valid_launches_for_sync = []
        for l_item in processed_launches:
            ts_ms = l_item.get('timestamp_ms') # Get the millisecond timestamp
            status = l_item.get('status')

            # A launch is valid for sync if:
            # 1. It has a timestamp_ms (None means it couldn't be parsed or is truly TBD and handled as None)
            #    OR
            # 2. Its status indicates it's scheduled or TBD (even if timestamp_ms is None or 0 for now)
            # The check `ts_ms is not None` correctly handles positive, negative, and zero timestamps.
            # `None` means we don't have a concrete time for it from parsing.
            if ts_ms is not None or status in ["Scheduled", "TBD"]:
                valid_launches_for_sync.append(l_item)
        # --- END OF MODIFIED LOGIC ---
        
        if not valid_launches_for_sync:
            logger.info("No launches with valid timestamps (timestamp_ms is not None) or a 'Scheduled'/'TBD' status to process.")
            if output_to_sync_file: # Create empty if specified
                os.makedirs(os.path.dirname(output_to_sync_file), exist_ok=True)
                with open(output_to_sync_file, 'w', encoding='utf-8') as f_empty:
                    json.dump([], f_empty)
            return
        
        # For oldest_timestamp_in_scrape, we should consider only non-None and convert to seconds for the logic
        # that multiplies by 1000 later. Or, more simply, keep it in ms for the filter.
        # Feishu filter expects milliseconds directly for "ExactDate".
        actual_timestamps_ms = [l.get('timestamp_ms') for l in valid_launches_for_sync if l.get('timestamp_ms') is not None]
        
        # oldest_timestamp_in_scrape should be in milliseconds for the Feishu filter
        oldest_timestamp_ms_in_scrape = min(actual_timestamps_ms) if actual_timestamps_ms else 0 
        # If all are None, oldest_timestamp_ms_in_scrape will be 0.
        # If 0 is a valid timestamp (1970-01-01), this is fine.
        # If you want to avoid filtering by time if only None timestamps exist, adjust this.

        filter_for_feishu = {"conditions": [], "conjunction": "and"}
        filter_for_feishu["conditions"].append({
            "field_name": "Source", "operator": "is", "value": [source_value_from_file]
        })

        # Only add time filter if we have a meaningful oldest timestamp.
        # If oldest_timestamp_ms_in_scrape is 0 AND actual_timestamps_ms was empty (meaning all were None or TBD with no time),
        # then we might not want to filter by time `isGreaterOrEqual` 0, as that's 1970-01-01.
        # However, if 0 is a legitimate earliest timestamp from your data, then filtering is correct.
        # Let's assume if actual_timestamps_ms is not empty, oldest_timestamp_ms_in_scrape is valid (can be negative, 0, or positive).
        if actual_timestamps_ms: # Only add date filter if there were actual timestamps
            filter_for_feishu["conditions"].append({
                "field_name": "发射日期时间", "operator": "isGreaterOrEqual", 
                "value": ["ExactDate", str(oldest_timestamp_ms_in_scrape)] # Use ms directly
            })
        else:
            logger.info("No actual timestamps found in valid launches; Feishu query will not filter by date.")

        
        helper = FeishuBitableHelper()
        # fields_to_fetch in helper.list_records is now List[str]
        fields_to_fetch = ["发射日期时间", "Source", "发射任务名称"]
        bitable_records_response = helper.list_records(
            filter=filter_for_feishu, 
            field_names=fields_to_fetch, # Pass as Python list
            page_size=500
        )
        
        existing_records_tuples = set()
        if bitable_records_response and bitable_records_response.items:
            for record in bitable_records_response.items:
                ts_millis_from_feishu = record.fields.get("发射日期时间") 
                rec_source_field = record.fields.get("Source") 
                rec_mission = record.fields.get("发射任务名称", "")
                rec_source_val = "Unknown"
                if isinstance(rec_source_field, str): rec_source_val = rec_source_field
                elif isinstance(rec_source_field, list) and rec_source_field: rec_source_val = rec_source_field[0]
                existing_records_tuples.add(
                    (ts_millis_from_feishu if ts_millis_from_feishu is not None else 0, 
                    rec_source_val, 
                    rec_mission.strip().lower())
                )
            logger.info(f"Found {len(existing_records_tuples)} existing records in Feishu matching criteria.")
        else:
            logger.info("No existing records found in Feishu matching criteria or failed to fetch.")
            
        new_launches_to_add_to_feishu = []
        for launch_item in valid_launches_for_sync:
            current_launch_tuple = (
                launch_item.get('timestamp_ms', 0), # Use 0 if 'timestamp_ms' is None for consistency with above
                launch_item.get('source_name'),
                launch_item.get('mission', "").strip().lower()
            )
            if current_launch_tuple not in existing_records_tuples:
                new_launches_to_add_to_feishu.append(launch_item)
        
        if new_launches_to_add_to_feishu:
            new_launches_to_add_to_feishu.sort(key=lambda x: x.get('timestamp_ms') if x.get('timestamp_ms') is not None else float('inf'))
            
        logger.info(f"Prepared {len(new_launches_to_add_to_feishu)} records for Feishu sync.")

        if output_to_sync_file is None:
            base_processed_file_name = os.path.splitext(os.path.basename(processed_file))[0]
            output_to_sync_file = f"{TO_SYNC_DATA_DIR}/{base_processed_file_name}_to_sync.json"

        os.makedirs(os.path.dirname(output_to_sync_file), exist_ok=True)
        with open(output_to_sync_file, 'w', encoding='utf-8') as f:
            json.dump(new_launches_to_add_to_feishu, f, ensure_ascii=False, indent=2)
        logger.info(f"Data to be synced saved to: {output_to_sync_file}")
        logger.info(f"Run 'execute-feishu-sync --to-sync-file \"{output_to_sync_file}\"' to upload to Feishu.")

    except Exception as e:
        logger.error(f"Failed to prepare Feishu sync data: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)

@app.command()
def execute_feishu_sync(
    to_sync_file: str = typer.Option(..., help="Path to the JSON file containing data to be synced (from prepare-feishu-sync)."),
    delay_between_adds: float = typer.Option(0.2, help="Delay in seconds between adding each record to Feishu."),
    enable_pre_add_check: bool = typer.Option(False, "--pre-add-check/--no-pre-add-check", help="Enable an additional check for record existence before each add operation.") # New option
):
    """Reads a 'to-sync' JSON file and adds records to Feishu, with resume capability."""
    try:
        if not os.path.exists(to_sync_file):
            logger.error(f"'To-sync' file not found: {to_sync_file}")
            raise typer.Exit(1)

        with open(to_sync_file, 'r', encoding='utf-8') as f:
            launches_to_sync = json.load(f)

        if not launches_to_sync:
            logger.info(f"No records in {to_sync_file} to sync. Exiting.")
            # ... (progress file cleanup logic remains the same) ...
            if os.path.exists(SYNC_PROGRESS_FILE):
                try:
                    with open(SYNC_PROGRESS_FILE, 'r') as pf: progress_data = json.load(pf)
                    if progress_data.get("source_file") == to_sync_file:
                        os.remove(SYNC_PROGRESS_FILE)
                        logger.info(f"Removed progress file {SYNC_PROGRESS_FILE} as sync is complete/empty.")
                except Exception: pass 
            return

        start_index = 0
        current_file_hash = generate_file_hash(to_sync_file)

        # ... (resume logic using SYNC_PROGRESS_FILE remains the same) ...
        if os.path.exists(SYNC_PROGRESS_FILE):
            try:
                with open(SYNC_PROGRESS_FILE, 'r') as f: progress = json.load(f)
                if progress.get("source_file") == to_sync_file and progress.get("file_hash") == current_file_hash:
                    start_index = progress.get("next_index", 0)
                    logger.info(f"Resuming sync from index {start_index} for file {to_sync_file}.")
                else:
                    logger.info(f"Progress file mismatch. Starting sync from beginning for {to_sync_file}.")
            except Exception as e:
                logger.warning(f"Error reading progress file {SYNC_PROGRESS_FILE}: {e}. Starting sync from beginning.")
        
        if start_index >= len(launches_to_sync):
            logger.info(f"All records from {to_sync_file} seem to be already processed. Exiting.")
            if os.path.exists(SYNC_PROGRESS_FILE): os.remove(SYNC_PROGRESS_FILE)
            return

        helper = FeishuBitableHelper()
        successfully_added_count = 0
        skipped_due_to_pre_check = 0 # Counter for skipped records
        total_to_process_this_run = len(launches_to_sync) - start_index

        logger.info(f"Starting Feishu sync. Total records in file: {len(launches_to_sync)}. Processing from index: {start_index}.")
        if enable_pre_add_check:
            logger.info("Pre-add existence check is ENABLED. This will increase API calls and processing time.")

        for i in range(start_index, len(launches_to_sync)):
            launch_to_add = launches_to_sync[i]
            
            # Save progress *before* attempting to add or check
            try:
                with open(SYNC_PROGRESS_FILE, 'w') as f:
                    json.dump({"source_file": to_sync_file, "file_hash": current_file_hash, "next_index": i}, f)
            except Exception as e_prog:
                logger.error(f"Critical error writing progress file {SYNC_PROGRESS_FILE}: {e_prog}. Aborting.")
                raise typer.Exit(1)

            record_already_exists = False
            if enable_pre_add_check:
                # --- Pre-add check logic ---
                logger.debug(f"Pre-add check for: {launch_to_add.get('mission', 'N/A')}")
                timestamp_ms_to_check = launch_to_add.get('timestamp_ms')
                source_to_check = launch_to_add.get('source_name')
                mission_to_check = launch_to_add.get('mission', "").strip().lower()

                if timestamp_ms_to_check is None or not source_to_check: # Cannot reliably check without these
                    logger.warning(f"Skipping pre-add check for record {i+1} due to missing timestamp_ms or source_name.")
                else:
                    # Construct filter for this specific record
                    # Using 'is' for exact match. Note: timestamp_ms_to_check can be negative.
                    # If timestamp_ms_to_check is 0 (epoch), it's a valid timestamp.
                    check_filter = {
                        "conditions": [
                            {"field_name": "发射日期时间", "operator": "is", "value": ["ExactDate", str(timestamp_ms_to_check)]},
                        ],
                        "conjunction": "and"
                    }
                    try:
                        # Only need to know if any record exists, so page_size 1 is fine.
                        # We only need record_id or any field to confirm existence.
                        existing_check_response = helper.list_records(
                            filter=check_filter, 
                            field_names=None, # Requesting minimal field
                            page_size=1
                        )
                        if len(existing_check_response) >= 1:
                            record_already_exists = True
                            logger.info(f"Record {i+1} '{launch_to_add.get('mission', 'N/A')}' already exists in Feishu (based on pre-add check). Skipping.")
                            skipped_due_to_pre_check += 1
                    except Exception as e_check:
                        # If the check itself fails, log it but proceed with the add attempt (conservative approach)
                        # as the record might not exist and the check failed for other reasons (e.g., temporary API issue).
                        logger.error(f"Pre-add check failed for record {i+1}: {e_check}. Will attempt to add.")
                # --- End of Pre-add check logic ---

            if record_already_exists:
                # If skipped by pre-add check, we still count it as "processed" for the progress file's next_index,
                # but not as "successfully_added_count".
                # The progress file update to 'next_index: i' already handles moving to the next item.
                # We just don't call add_launch_to_bitable.
                pass
            else:
                logger.info(f"Attempting to add record {i+1}/{len(launches_to_sync)}: {launch_to_add.get('mission', 'N/A')}")
                result = helper.add_launch_to_bitable(launch_to_add)
                if result:
                    successfully_added_count += 1
                else:
                    logger.error(f"Failed to add record {i+1}: {launch_to_add.get('mission', 'N/A')}. Will retry on next run if script restarts.")
            
            # Update progress file to indicate this item is done, and next is i+1
            try:
                with open(SYNC_PROGRESS_FILE, 'w') as f:
                    json.dump({"source_file": to_sync_file, "file_hash": current_file_hash, "next_index": i + 1}, f)
            except Exception as e_prog: # Should be very rare if first write succeeded
                logger.error(f"Critical error updating progress file {SYNC_PROGRESS_FILE} after processing item {i}: {e_prog}.")
                # Decide if to abort or continue. If this fails, resume might process last item again.
                # For now, log and continue.


            if i < len(launches_to_sync) - 1 and delay_between_adds > 0:
                time.sleep(delay_between_adds)
        
        logger.info(f"Feishu sync execution finished for {to_sync_file}.")
        if enable_pre_add_check:
            logger.info(f"Skipped {skipped_due_to_pre_check} records due to pre-add existence check.")
        logger.info(f"Successfully added {successfully_added_count} records in this run.")
        logger.info(f"Total records processed (added or skipped by pre-check) in this run: {skipped_due_to_pre_check + successfully_added_count} out of {total_to_process_this_run} pending.")


        # Sync completed (or all items in the file iterated through), remove/update progress file
        if os.path.exists(SYNC_PROGRESS_FILE):
            try:
                # Check if the progress file's next_index indeed points to the end of the list
                is_fully_completed = False
                with open(SYNC_PROGRESS_FILE, 'r') as f_prog_check:
                    final_progress = json.load(f_prog_check)
                if final_progress.get("source_file") == to_sync_file and \
                final_progress.get("file_hash") == current_file_hash and \
                final_progress.get("next_index") == len(launches_to_sync):
                    is_fully_completed = True

                if is_fully_completed:
                    os.remove(SYNC_PROGRESS_FILE)
                    logger.info(f"Removed progress file {SYNC_PROGRESS_FILE} as sync is fully complete.")
                else:
                    logger.warning(f"Progress file {SYNC_PROGRESS_FILE} indicates sync for {to_sync_file} is not fully complete (next_index: {final_progress.get('next_index')}, total: {len(launches_to_sync)}). Not removing.")
            except Exception as e_clean:
                logger.warning(f"Could not verify or remove progress file {SYNC_PROGRESS_FILE} after completion: {e_clean}")

    except Exception as e:
        logger.error(f"Failed to execute Feishu sync: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)


@app.command()
def test_list_records(
    table_id_override: Optional[str] = typer.Option(None, help="Override BITABLE_TABLE_ID from .env for this test."),
    view_id_override: Optional[str] = typer.Option(None, help="Override BITABLE_VIEW_ID from .env for this test."),
    filter_json: Optional[str] = typer.Option(None, help="JSON string for the filter conditions (e.g., '{\"conditions\":[{\"field_name\":\"Source\",\"operator\":\"is\",\"value\":[\"nextspaceflight.com\"]}]}')"),
    fields_json: Optional[str] = typer.Option(None, help="JSON string for field_names to retrieve (e.g., '[\"发射任务名称\", \"Source\"]')"),
    page_size: int = typer.Option(20, help="Number of records to retrieve per page (max 500 for search)."),
    max_total_records: int = typer.Option(100, help="Maximum total records to fetch for this test to avoid large dumps.")
):
    """Tests the FeishuBitableHelper.list_records() method by fetching some records."""
    logger.info("--- Testing FeishuBitableHelper.list_records() ---")
    try:
        helper = FeishuBitableHelper()

        # Override table_id and view_id if provided via CLI options
        if table_id_override:
            logger.info(f"Overriding table_id with: {table_id_override}")
            helper.table_id = table_id_override
        if view_id_override:
            logger.info(f"Overriding view_id with: {view_id_override}")
            helper.view_id = view_id_override
        
        logger.info(f"Using App Token: ...{helper.app_token[-6:] if helper.app_token else 'N/A'}") # Show last 6 chars
        logger.info(f"Using Table ID: {helper.table_id}")
        logger.info(f"Using View ID: {helper.view_id if helper.view_id else 'Not set (will use default view)'}")


        parsed_filter = None
        if filter_json:
            try:
                parsed_filter = json.loads(filter_json)
                logger.info(f"Using custom filter: {json.dumps(parsed_filter, indent=2)}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON for filter: {e}")
                raise typer.Exit(1)

        parsed_fields_list_for_helper = None # This will be List[str] or None
        if fields_json:
            try:
                parsed_fields_list_for_helper = json.loads(fields_json)
                if not isinstance(parsed_fields_list_for_helper, list) or \
                not all(isinstance(item, str) for item in parsed_fields_list_for_helper):
                    logger.error("Fields JSON must be a list of strings (e.g., '[\"Field A\", \"Field B\"]').")
                    raise typer.Exit(1)
                logger.info(f"Requesting specific fields: {parsed_fields_list_for_helper}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON for fields: {e}")
                raise typer.Exit(1)
        
        logger.info(f"Calling helper.list_records with page_size={page_size}...")
        records_response_data = helper.list_records(
            filter=parsed_filter, 
            field_names=parsed_fields_list_for_helper, # Pass the Python list
            page_size=page_size
        )

        if records_response_data and hasattr(records_response_data, 'items') and records_response_data.items:
            all_items = records_response_data.items
            logger.info(f"Successfully retrieved {len(all_items)} total records matching criteria.")
            
            records_to_display = all_items[:max_total_records]
            
            if not records_to_display:
                logger.info("No records to display (possibly empty or all filtered out by max_total_records).")
            else:
                logger.info(f"Displaying first {len(records_to_display)} records (or less if total < max_total_records):")
                for i, record in enumerate(records_to_display):
                    record_id = getattr(record, 'record_id', 'N/A')
                    fields = getattr(record, 'fields', {})
                    logger.info(f"--- Record {i+1} (Record ID: {record_id}) ---")
                    logger.info(json.dumps(fields, indent=2, ensure_ascii=False))
            
            if len(all_items) > max_total_records:
                logger.info(f"... and {len(all_items) - max_total_records} more records not displayed due to max_total_records limit.")

        elif records_response_data and hasattr(records_response_data, 'items') and not records_response_data.items:
            logger.info("Successfully called API, but no records were returned (list is empty).")
        else:
            logger.error("Failed to retrieve records or response was not in expected format. Check previous logs from FeishuBitableHelper.")

    except ValueError as ve: # Catch ValueError from FeishuBitableHelper init (missing env vars)
        logger.error(f"Configuration error: {ve}")
        logger.error("Please ensure FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID are set in your .env file.")
        raise typer.Exit(1)
    except Exception as e:
        logger.error(f"An error occurred during test_list_records: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)
    finally:
        logger.info("--- test_list_records() finished ---")

@app.command()
def run_daily_sync_flow( # Renamed to reflect it runs the flow once
    source: LaunchSource = typer.Option(LaunchSource.NEXTSPACEFLIGHT, help="The data source to sync."),
    fetch_all_pages: bool = typer.Option(False, "--all-pages/--single-page", help="For NextSpaceflight: fetch all pages during fetch-data."),
    max_pages_nsf: int = typer.Option(50, help="Max pages for NextSpaceflight if --all-pages is enabled."),
    execute_delay: float = typer.Option(0.5, help="Delay between adds during execute-feishu-sync."),
    execute_pre_check: bool = typer.Option(True, "--pre-add-check/--no-pre-add-check", help="Enable pre-add check during execute-feishu-sync.") # Defaulting to True for safety in scheduled task
):
    """
    Runs the full data syncronization flow once: fetch, prepare, and execute.
    This command is intended to be called by an external scheduler (e.g., cron).
    """
    logger.info(f"--- Starting Daily Sync Flow for Source: {source.value} ---")
    
    # --- Step 1: Fetch Data ---
    logger.info("Step 1: Fetching data...")
    # Determine default output file for fetch_data based on source and all_pages
    safe_source_name = "".join(c if c.isalnum() else "_" for c in source.value)
    all_pages_suffix = "_all_pages" if fetch_all_pages and source == LaunchSource.NEXTSPACEFLIGHT else ""
    default_processed_file = f"{PROCESSED_DATA_DIR}/{safe_source_name}_processed{all_pages_suffix}.json"
    
    try:
        # It's cleaner to call the function directly rather than subprocess or app.invoke for internal calls
        fetch_data(
            source=source, 
            all_pages=fetch_all_pages, 
            max_pages_nextspaceflight=max_pages_nsf,
            output_file=default_processed_file # Pass the determined output file
        )
        logger.info(f"Fetch data successful. Output: {default_processed_file}")
    except typer.Exit as e: # Catch Exit from fetch_data
        if e.exit_code == 0:
            logger.info("Fetch data completed (possibly with non-error exit).")
        else:
            logger.error(f"Fetch data step failed with exit code {e.exit_code}. Aborting daily sync flow.")
            raise # Re-raise to stop the flow
    except Exception as e:
        logger.error(f"Fetch data step failed: {e}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1) # Exit with error

    # Check if the processed file was created and has content
    if not os.path.exists(default_processed_file) or os.path.getsize(default_processed_file) == 0:
        logger.warning(f"Processed file {default_processed_file} is missing or empty after fetch step. Sync flow might not proceed meaningfully.")
        # Depending on requirements, you might want to exit here or let prepare_feishu_sync handle empty input.
        # prepare_feishu_sync already handles empty input gracefully.

    # --- Step 2: Prepare Feishu Sync ---
    logger.info("Step 2: Preparing data for Feishu sync...")
    base_processed_file_name = os.path.splitext(os.path.basename(default_processed_file))[0]
    default_to_sync_file = f"{TO_SYNC_DATA_DIR}/{base_processed_file_name}_to_sync.json"

    try:
        prepare_feishu_sync(
            processed_file=default_processed_file,
            output_to_sync_file=default_to_sync_file # Pass the determined output file
        )
        logger.info(f"Prepare Feishu sync successful. Output: {default_to_sync_file}")
    except typer.Exit as e:
        if e.exit_code == 0:
            logger.info("Prepare feishu sync completed (possibly with non-error exit).")
        else:
            logger.error(f"Prepare Feishu sync step failed with exit code {e.exit_code}. Aborting daily sync flow.")
            raise
    except Exception as e:
        logger.error(f"Prepare Feishu sync step failed: {e}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)

    # Check if the to_sync file was created
    if not os.path.exists(default_to_sync_file):
        logger.warning(f"'To-sync' file {default_to_sync_file} was not created. This might be normal if no new records were found.")
        # execute_feishu_sync handles empty/missing to_sync file.

    # --- Step 3: Execute Feishu Sync ---
    logger.info("Step 3: Executing Feishu sync...")
    try:
        # Only proceed if the to_sync_file actually exists and has content,
        # or let execute_feishu_sync handle it (it does log if file is empty/missing).
        if os.path.exists(default_to_sync_file) and os.path.getsize(default_to_sync_file) > 0:
            execute_feishu_sync(
                to_sync_file=default_to_sync_file,
                delay_between_adds=execute_delay,
                enable_pre_add_check=execute_pre_check
            )
            logger.info("Execute Feishu sync step completed.")
        elif os.path.exists(default_to_sync_file) and os.path.getsize(default_to_sync_file) == 0:
            logger.info(f"'To-sync' file {default_to_sync_file} is empty. No records to execute.")
            # Clean up progress file if it was for an empty to_sync file (execute_feishu_sync handles this)
            execute_feishu_sync(to_sync_file=default_to_sync_file) # Call it to trigger its empty file handling
        else:
            logger.info(f"'To-sync' file {default_to_sync_file} not found or inaccessible. Skipping execute step.")

    except typer.Exit as e:
        if e.exit_code == 0:
            logger.info("Execute feishu sync completed (possibly with non-error exit).")
        else:
            logger.error(f"Execute Feishu sync step failed with exit code {e.exit_code}.")
            # No need to re-raise, as this is the last step. Error is already logged.
    except Exception as e:
        logger.error(f"Execute Feishu sync step failed: {e}")
        logger.error(traceback.format_exc())
        # No need to re-raise, as this is the last step. Error is already logged.

    logger.info(f"--- Daily Sync Flow for Source: {source.value} Finished ---")

@app.command()
def hello(name: Optional[str] = typer.Argument(None)):
    """Simple greeting command"""
    if name:
        logger.info(f"Hello {name}! / 你好 {name}!")
    else:
        logger.info("Hello World! / 你好 世界!")


if __name__ == "__main__":
    app()