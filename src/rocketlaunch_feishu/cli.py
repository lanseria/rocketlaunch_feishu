# src/rocketlaunch_feishu/cli.py
import typer
from typing import Optional, List, Tuple # Added Tuple
import os
import traceback
import httpx
import re  # Required for regular expressions
from .html_parser import parse_launches_nextspaceflight # Only import nextspaceflight parser
import json
import schedule # New import
# Removed: timedelta (if not used elsewhere)
from datetime import datetime 
import time
from zoneinfo import ZoneInfo
from .feishu_bitable import FeishuBitableHelper
import logging
from logging.handlers import RotatingFileHandler
from enum import Enum
from bs4 import BeautifulSoup 
import hashlib

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
    # ROCKETLAUNCH_LIVE = "rocketlaunch.live" # Removed
    NEXTSPACEFLIGHT = "nextspaceflight.com" # Now the only source

# Removed: parse_datetime_rocketlaunchlive_dict

# --- CONFIGURABLE FILE PATHS (no change) ---
PROCESSED_DATA_DIR = "data/processed_launches"
TO_SYNC_DATA_DIR = "data/to_sync_launches"
SYNC_PROGRESS_FILE = "data/sync_progress.json"
os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
os.makedirs(TO_SYNC_DATA_DIR, exist_ok=True)
os.makedirs("data/html", exist_ok=True)
os.makedirs("data/raw", exist_ok=True)

def download_html_for_source(
    # source: LaunchSource, # No longer needed as param if only one source
    all_pages: bool = False,
    max_pages_nextspaceflight: int = 236 
) -> str:
    source_value = LaunchSource.NEXTSPACEFLIGHT.value # Hardcode or get from Enum
    output_dir = "data/html"
    # os.makedirs(output_dir, exist_ok=True) # Already done globally
    safe_source_name = "".join(c if c.isalnum() else "_" for c in source_value)
    all_pages_suffix = "_all_pages" if all_pages else ""
    raw_html_output_file = f"{output_dir}/{safe_source_name}_latest_downloaded{all_pages_suffix}.html"

    combined_html_content = ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client: # Increased timeout slightly
            # Logic for NEXTSPACEFLIGHT only
            base_url = "https://nextspaceflight.com/launches/past/"
            if not all_pages:
                logger.info(f"Downloading data from {base_url} (page 1) for source {source_value}...")
                response = client.get(base_url, headers=headers)
                response.raise_for_status()
                combined_html_content = response.text
            else:
                logger.info(f"Downloading all pages from {base_url} for source {source_value}...")
                all_launch_cards_html = []
                for page_num in range(1, max_pages_nextspaceflight + 1):
                    page_url = f"{base_url}?page={page_num}&search="
                    logger.info(f"Downloading page {page_num}/{max_pages_nextspaceflight}: {page_url}")
                    if page_num > 1: time.sleep(1.5) # Slightly increased delay for politeness
                    response = client.get(page_url, headers=headers)
                    response.raise_for_status()
                    page_content = response.text
                    soup = BeautifulSoup(page_content, 'html.parser')
                    
                    # More robust check for end of results
                    if soup.find(text=re.compile(r"No\s+more\s+results!", re.IGNORECASE)):
                        logger.info(f"No more results found at page {page_num}. Stopping.")
                        break
                    
                    # Refined selector from html_parser
                    current_page_cards = soup.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split() and 'mdl-cell' not in x.split())

                    if not current_page_cards and page_num > 1 : # If not first page and no cards, likely end
                        logger.info(f"No launch cards found on page {page_num} (and no 'No more results' text). Assuming end of data.")
                        break
                    for card_div in current_page_cards:
                        all_launch_cards_html.append(str(card_div))
                    if page_num == max_pages_nextspaceflight:
                        logger.warning(f"Reached max_pages limit ({max_pages_nextspaceflight}) for NextSpaceflight.")
                if all_launch_cards_html:
                    combined_html_content = f"<html><head><meta charset='utf-8'></head><body><div class='mdl-grid'>{''.join(all_launch_cards_html)}</div></body></html>"
                else:
                    combined_html_content = "<html><body></body></html>"
            # Removed ROCKETLAUNCH_LIVE branch

        with open(raw_html_output_file, "w", encoding="utf-8") as f:
            f.write(combined_html_content)
        logger.info(f"Raw HTML data saved to {raw_html_output_file}")
        return raw_html_output_file
    except httpx.HTTPStatusError as hse:
        logger.error(f"HTTP error {hse.response.status_code} for {hse.request.url} - {hse.response.text[:200]}")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.error(f"Download failed for {source_value}: {str(e)}")
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
    # source: LaunchSource = typer.Option(..., help="The data source to fetch from."), # No longer needed if only one source
    all_pages: bool = typer.Option(False, "--all-pages/--single-page", help="Fetch all pages from NextSpaceflight."),
    max_pages_nextspaceflight: int = typer.Option(236, help="Safety limit for 'all_pages' with NextSpaceflight."),
    output_file: Optional[str] = typer.Option(None, help="Override default output JSON file path for processed data.")
):
    """Downloads HTML from NextSpaceflight.com, parses it, and saves structured launch data."""
    source = LaunchSource.NEXTSPACEFLIGHT # Hardcoded
    try:
        logger.info(f"Starting data fetching for source: {source.value}")
        raw_html_file = download_html_for_source( # Pass source implicitly now
            all_pages=all_pages, 
            max_pages_nextspaceflight=max_pages_nextspaceflight
        )

        if not os.path.exists(raw_html_file) or os.path.getsize(raw_html_file) == 0:
            logger.error(f"Downloaded HTML file {raw_html_file} is empty or not found. Aborting fetch.")
            raise typer.Exit(1)

        with open(raw_html_file, 'r', encoding='utf-8') as f:
            html_data = f.read()

        # Parse HTML - only NEXTSPACEFLIGHT logic needed
        processed_launches = parse_launches_nextspaceflight(html_data, source.value)
        
        logger.info(f"Parsed {len(processed_launches)} launch records from {source.value}")
        
        if output_file is None:
            safe_source_name = "".join(c if c.isalnum() else "_" for c in source.value)
            all_pages_suffix = "_all_pages" if all_pages else ""
            output_file = f"{PROCESSED_DATA_DIR}/{safe_source_name}_processed{all_pages_suffix}.json"
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(processed_launches, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully fetched and processed data. Saved to: {output_file}")

    except Exception as e:
        logger.error(f"Data fetching process failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise typer.Exit(1)

@app.command()
def prepare_feishu_sync(
    processed_file: str = typer.Option(..., help="Path to the JSON file (from fetch-data for NextSpaceflight)."),
    output_to_sync_file: Optional[str] = typer.Option(None, help="Override default output JSON file path for 'to-sync' data.")
):
    """Compares NextSpaceflight launch data with Feishu and prepares records for sync."""
    # ... (existing logic, source_value_from_file will be 'nextspaceflight.com') ...
    # The logic inside should still work fine.
    # One check: `source_value_from_file = processed_launches[0].get('source_name')`
    # This assumes `parse_launches_nextspaceflight` correctly sets `source_name`.
    # It does: `launches.append({'source_name': source_name, ...})`
    # The rest of prepare_feishu_sync logic doesn't inherently depend on multiple sources
    # other than using this source_value_from_file for filtering Feishu.
    # So, it should remain largely the same.
    try:
        if not os.path.exists(processed_file): # ... (same)
            logger.error(f"Processed data file not found: {processed_file}")
            raise typer.Exit(1)

        with open(processed_file, 'r', encoding='utf-8') as f: # ... (same)
            processed_launches = json.load(f)

        if not processed_launches: # ... (same)
            logger.info(f"No launches in {processed_file} to prepare for sync. Exiting.")
            if output_to_sync_file:
                os.makedirs(os.path.dirname(output_to_sync_file), exist_ok=True)
                with open(output_to_sync_file, 'w', encoding='utf-8') as f_empty: json.dump([], f_empty)
            return

        source_value_from_file = processed_launches[0].get('source_name') # ... (same)
        if not source_value_from_file or source_value_from_file != LaunchSource.NEXTSPACEFLIGHT.value:
            logger.error(f"Source mismatch or missing in {processed_file}. Expected '{LaunchSource.NEXTSPACEFLIGHT.value}'.")
            raise typer.Exit(1)
        
        logger.info(f"Preparing Feishu sync for data from file: {processed_file} (Source: {source_value_from_file})")

        valid_launches_for_sync = [] # ... (same logic using timestamp_ms) ...
        for l_item in processed_launches:
            ts_ms = l_item.get('timestamp_ms'); status = l_item.get('status')
            if ts_ms is not None or status in ["Scheduled", "TBD"]: valid_launches_for_sync.append(l_item)
        
        if not valid_launches_for_sync: # ... (same) ...
            logger.info("No launches with valid timestamps or 'Scheduled'/'TBD' status to process.")
            if output_to_sync_file:
                os.makedirs(os.path.dirname(output_to_sync_file), exist_ok=True)
                with open(output_to_sync_file, 'w', encoding='utf-8') as f_empty: json.dump([], f_empty)
            return
        
        actual_timestamps_ms = [l.get('timestamp_ms') for l in valid_launches_for_sync if l.get('timestamp_ms') is not None] # ... (same)
        oldest_timestamp_ms_in_scrape = min(actual_timestamps_ms) if actual_timestamps_ms else 0  # ... (same)

        filter_for_feishu = {"conditions": [], "conjunction": "and"} # ... (same)
        filter_for_feishu["conditions"].append({"field_name": "Source", "operator": "is", "value": [source_value_from_file]})
        if actual_timestamps_ms: # ... (same)
            filter_for_feishu["conditions"].append({"field_name": "发射日期时间", "operator": "isGreater", "value": ["ExactDate", str(oldest_timestamp_ms_in_scrape)]})
        else: logger.info("No actual timestamps found; Feishu query will not filter by date.")

        helper = FeishuBitableHelper() # ... (same)
        fields_to_fetch = ["发射日期时间", "Source", "发射任务名称"]
        bitable_records_response = helper.list_records(filter=filter_for_feishu, field_names=fields_to_fetch, page_size=500)
        
        existing_records_tuples = set() # ... (same logic) ...
        # print((bitable_records_response))
        if bitable_records_response:
            for record in bitable_records_response:
                print(record)
                fields = record["fields"]  # 确保用字典访问

                # 处理 发射日期时间（可能为 None）
                ts_millis_from_feishu = fields.get("发射日期时间", 0) or 0

                # 处理 Source（可能是 str 或 list）
                rec_source_field = fields.get("Source", "Unknown")
                rec_source_val = "Unknown"
                if isinstance(rec_source_field, str):
                    rec_source_val = rec_source_field
                elif isinstance(rec_source_field, list) and rec_source_field:
                    rec_source_val = rec_source_field[0]

                # 处理 发射任务名称（可能是富文本列表）
                rec_mission = fields.get("发射任务名称", "")
                if isinstance(rec_mission, list) and rec_mission and isinstance(rec_mission[0], dict):
                    rec_mission = rec_mission[0].get("text", "")
                elif not isinstance(rec_mission, str):
                    rec_mission = str(rec_mission)

                existing_records_tuples.add((
                    ts_millis_from_feishu,
                    rec_source_val,
                    rec_mission.strip().lower()
                ))
            logger.info(f"Found {len(existing_records_tuples)} existing records in Feishu matching criteria.")
        else:
            logger.info("No existing records found in Feishu matching criteria or failed to fetch.")
            
        new_launches_to_add_to_feishu = [] # ... (same logic) ...
        for launch_item in valid_launches_for_sync:
            current_launch_tuple = (launch_item.get('timestamp_ms', 0), launch_item.get('source_name'), launch_item.get('mission', "").strip().lower())
            if current_launch_tuple not in existing_records_tuples: new_launches_to_add_to_feishu.append(launch_item)
        
        if new_launches_to_add_to_feishu: # ... (same logic) ...
            new_launches_to_add_to_feishu.sort(key=lambda x: x.get('timestamp_ms') if x.get('timestamp_ms') is not None else float('inf'))
        logger.info(f"Prepared {len(new_launches_to_add_to_feishu)} records for Feishu sync.")

        if output_to_sync_file is None: # ... (same logic) ...
            base_processed_file_name = os.path.splitext(os.path.basename(processed_file))[0]
            output_to_sync_file = f"{TO_SYNC_DATA_DIR}/{base_processed_file_name}_to_sync.json"
        os.makedirs(os.path.dirname(output_to_sync_file), exist_ok=True) # ... (same logic) ...
        with open(output_to_sync_file, 'w', encoding='utf-8') as f: json.dump(new_launches_to_add_to_feishu, f, ensure_ascii=False, indent=2)
        logger.info(f"Data to be synced saved to: {output_to_sync_file}")
    except Exception as e: # ... (same logic) ...
        logger.error(f"Failed to prepare Feishu sync data: {str(e)}"); logger.error(traceback.format_exc()); raise typer.Exit(1)

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
def run_daily_sync_flow(
    fetch_all_pages: bool = typer.Option(False, "--all-pages/--single-page", help="Fetch all pages from NextSpaceflight."),
    max_pages_nsf: int = typer.Option(236, help="Max pages for NextSpaceflight if --all-pages is enabled."), # Default updated
    execute_delay: float = typer.Option(0.5, help="Delay between adds during execute-feishu-sync."),
    execute_pre_check: bool = typer.Option(True, "--pre-add-check/--no-pre-add-check", help="Enable pre-add check.")
):
    """
    Runs the full data sync flow once for NextSpaceflight.com.
    Intended for external schedulers.
    """
    source_to_sync = LaunchSource.NEXTSPACEFLIGHT # Hardcoded
    logger.info(f"--- Starting Daily Sync Flow for Source: {source_to_sync.value} ---")
    
    logger.info("Step 1: Fetching data...")
    safe_source_name = "".join(c if c.isalnum() else "_" for c in source_to_sync.value)
    all_pages_suffix = "_all_pages" if fetch_all_pages else ""
    default_processed_file = f"{PROCESSED_DATA_DIR}/{safe_source_name}_processed{all_pages_suffix}.json"
    
    try:
        fetch_data( # Call directly
            all_pages=fetch_all_pages, 
            max_pages_nextspaceflight=max_pages_nsf,
            output_file=default_processed_file
        )
        logger.info(f"Fetch data successful. Output: {default_processed_file}")
    except typer.Exit as e:
        if e.exit_code != 0: logger.error(f"Fetch data step failed. Aborting."); raise
    except Exception as e:
        logger.error(f"Fetch data step failed: {e}\n{traceback.format_exc()}"); raise typer.Exit(1)

    if not os.path.exists(default_processed_file) or os.path.getsize(default_processed_file) == 0:
        logger.warning(f"Processed file {default_processed_file} missing or empty. Flow may not proceed.")

    logger.info("Step 2: Preparing data for Feishu sync...")
    base_processed_file_name = os.path.splitext(os.path.basename(default_processed_file))[0]
    default_to_sync_file = f"{TO_SYNC_DATA_DIR}/{base_processed_file_name}_to_sync.json"

    try:
        prepare_feishu_sync(processed_file=default_processed_file, output_to_sync_file=default_to_sync_file)
        logger.info(f"Prepare Feishu sync successful. Output: {default_to_sync_file}")
    except typer.Exit as e:
        if e.exit_code != 0: logger.error(f"Prepare Feishu sync step failed. Aborting."); raise
    except Exception as e:
        logger.error(f"Prepare Feishu sync step failed: {e}\n{traceback.format_exc()}"); raise typer.Exit(1)

    if not os.path.exists(default_to_sync_file):
        logger.warning(f"'To-sync' file {default_to_sync_file} not created. Skipping execute step.")
        logger.info(f"--- Daily Sync Flow for Source: {source_to_sync.value} Finished (no data to execute) ---")
        return

    logger.info("Step 3: Executing Feishu sync...")
    try:
        if os.path.getsize(default_to_sync_file) > 0:
            execute_feishu_sync(
                to_sync_file=default_to_sync_file,
                delay_between_adds=execute_delay,
                enable_pre_add_check=execute_pre_check
            )
        else: # File exists but is empty
            logger.info(f"'To-sync' file {default_to_sync_file} is empty. No records to execute.")
            execute_feishu_sync(to_sync_file=default_to_sync_file) # Trigger empty file handling
        logger.info("Execute Feishu sync step completed.")
    except typer.Exit as e:
        if e.exit_code != 0: logger.error(f"Execute Feishu sync step failed.")
    except Exception as e:
        logger.error(f"Execute Feishu sync step failed: {e}\n{traceback.format_exc()}")

    logger.info(f"--- Daily Sync Flow for Source: {source_to_sync.value} Finished ---")


@app.command()
def start_scheduler( # New command to run the internal scheduler
    schedule_type: str = typer.Option("weekly", help="Type of schedule ('daily' or 'weekly')."),
    # Weekly params
    weekday: int = typer.Option(0, help="Weekly: Day of week (0=Mon..6=Sun)."), # Default Monday
    # Daily/Weekly time params
    hour: int = typer.Option(3, help="Hour to run (0-23)."), # Default 3 AM
    minute: int = typer.Option(0, help="Minute to run (0-59)."), # Default 00
    # Parameters for run_daily_sync_flow
    fetch_all_pages: bool = typer.Option(False, help="Fetch all pages."),
    max_pages_nsf: int = typer.Option(236, help="Max pages for NextSpaceflight."),
    execute_delay: float = typer.Option(0.3, help="Delay between Feishu adds."),
    execute_pre_check: bool = typer.Option(True, help="Enable Feishu pre-add check.")
):
    """
    Starts an internal scheduler to run the sync flow daily or weekly.
    WARNING: Less robust than system cron. Best for simple use cases or testing.
    """
    logger.info(f"--- Internal Scheduler ({schedule_type.upper()}) Started ---")
    
    job_args = {
        "fetch_all_pages": fetch_all_pages,
        "max_pages_nsf": max_pages_nsf,
        "execute_delay": execute_delay,
        "execute_pre_check": execute_pre_check,
    }

    # Define the job function with current arguments
    def job():
        logger.info(f"Scheduler: Triggering run_daily_sync_flow at {datetime.now()}")
        try:
            run_daily_sync_flow(**job_args) # Pass parameters
            logger.info("Scheduler: run_daily_sync_flow completed successfully.")
        except typer.Exit as te:
            if te.exit_code == 0: logger.info("Scheduler: run_daily_sync_flow exited cleanly.")
            else: logger.error(f"Scheduler: run_daily_sync_flow exited with code {te.exit_code}.")
        except Exception as e:
            logger.error(f"Scheduler: Error during scheduled run_daily_sync_flow: {e}")
            logger.error(traceback.format_exc())


    time_str = f"{hour:02d}:{minute:02d}"
    # Get the timezone string from environment or default
    tz_str = os.getenv("TZ", "Asia/Shanghai") # Ensure TZ env var is set correctly
    logger.info(f"Using timezone string for scheduler: {tz_str}")

    if schedule_type.lower() == "daily":
        schedule.every().day.at(time_str, tz=tz_str).do(job) # <--- Pass tz_str
        logger.info(f"Scheduled to run daily at {time_str} (TZ: {tz_str}).")
    elif schedule_type.lower() == "weekly":
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if not (0 <= weekday <= 6):
            logger.error("Invalid weekday. Must be 0 (Monday) to 6 (Sunday).")
            raise typer.Exit(1)
        
        day_to_schedule = days[weekday]
        
        scheduler_method = getattr(schedule.every(), day_to_schedule)
        scheduler_method.at(time_str, tz=tz_str).do(job) # <--- Pass tz_str
        
        logger.info(f"Scheduled to run every {day_to_schedule.capitalize()} at {time_str} (TZ: {tz_str}).")
    else:
        logger.error(f"Unsupported schedule_type: {schedule_type}. Use 'daily' or 'weekly'.")
        raise typer.Exit(1)

    logger.info("Scheduler is running. Press Ctrl+C to exit.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1) # Check every second
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
    finally:
        schedule.clear()

@app.command()
def hello(name: Optional[str] = typer.Argument(None)):
    """Simple greeting command"""
    if name:
        logger.info(f"Hello {name}! / 你好 {name}!")
    else:
        logger.info("Hello World! / 你好 世界!")


if __name__ == "__main__":
    app()