from bs4 import BeautifulSoup, Tag
import re
from datetime import datetime
from zoneinfo import ZoneInfo # Using ZoneInfo
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def parse_and_convert_datetime(
    year: int, 
    month: int, 
    day: int, 
    time_str: str, # e.g., "02:47"
    am_pm: str,    # e.g., "AM", "PM", or "" if 24h format
    input_timezone_str: str = "UTC", # Assume input time is UTC by default for rocketlaunch.live
    target_timezone_str: str = "Asia/Shanghai" # Target timezone for timestamp and string
) -> tuple[Optional[int], Optional[str]]:
    """
    Parses date/time components, converts to target timezone, and returns ms timestamp and string.
    Timestamp can be negative if date is before 1970 and Feishu supports it.
    """
    try:
        # Construct datetime string for strptime
        dt_format = "%Y-%m-%d %I:%M %p" if am_pm else "%Y-%m-%d %H:%M"
        datetime_input_str = f"{year}-{month:02d}-{day:02d} {time_str} {am_pm}".strip()
        
        # Create naive datetime object first
        dt_naive = datetime.strptime(datetime_input_str, dt_format)
        
        # Localize to input timezone
        input_tz = ZoneInfo(input_timezone_str)
        dt_localized_input = dt_naive.replace(tzinfo=input_tz)
        
        # Convert to target timezone
        target_tz = ZoneInfo(target_timezone_str)
        dt_target = dt_localized_input.astimezone(target_tz)
        
        # Generate millisecond timestamp (can be negative)
        # Python's timestamp() gives seconds since epoch.
        timestamp_ms = int(dt_target.timestamp() * 1000)
        
        # Generate a standard ISO-like string representation in the target timezone
        datetime_iso_str = dt_target.strftime("%Y-%m-%d %H:%M:%S %Z%z")

        if dt_target.year < 1970:
            logger.info(f"Date {dt_target.strftime('%Y-%m-%d')} is before 1970. Generated timestamp: {timestamp_ms} ms.")
        
        return timestamp_ms, datetime_iso_str

    except ValueError as ve: # Specific error for strptime issues
        logger.warning(f"Date/time string parsing failed for Y:{year} M:{month} D:{day} T:{time_str} {am_pm} (Format: {dt_format}): {ve}")
        return None, None
    except Exception as e:
        logger.warning(f"Generic datetime processing error for Y:{year} M:{month} D:{day} T:{time_str} {am_pm}: {e}")
        return None, None


def parse_datetime_rocketlaunchlive_dict(obj: dict) -> tuple[Optional[int], Optional[str]]:
    date_str = obj.get('date', '')
    time_str_raw = obj.get('time', '')
    
    if not date_str or not time_str_raw:
        return None, None # Indicate parsing failure

    current_year = datetime.now().year # Default year if not specified in date_str
    date_match = re.match(r'([A-Z]{3,}) ?(\d{1,2})(?: (\d{4}))?', date_str) 
    if not date_match:
        logger.warning(f"RL.live Date parsing failed for: {date_str}")
        return None, None
        
    month_str_abbr, day_s, year_s = date_match.groups()
    month_map = {m: i for i, m in enumerate(['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'], 1)}
    month_i = month_map.get(month_str_abbr.upper()[:3]) # Use first 3 chars for month
    if not month_i:
        logger.warning(f"RL.live Month parsing failed for: {month_str_abbr}")
        return None, None
        
    day_i = int(day_s)
    year_i = int(year_s) if year_s else current_year
        
    time_parts = time_str_raw.split(" ")
    time_val_extracted = time_parts[0] # HH:MM
    am_pm_extracted = ""
    # Example: "02:47 AM EDT", "10:00 PM UTC", "10:00 PM"
    # Current logic assumes the time string (e.g., "02:47 AM") is in UTC if no explicit timezone parsing for EDT/PDT etc.
    # If rocketlaunch.live actually provides times in local (e.g. EDT), input_timezone_str would need to be dynamic.
    # For now, we stick to the original assumption that the base time is UTC.
    if len(time_parts) > 1 and (time_parts[1].upper() == "AM" or time_parts[1].upper() == "PM"):
        am_pm_extracted = time_parts[1].upper()
    
    # Assuming rocketlaunch.live times (after AM/PM parsing) are effectively UTC
    return parse_and_convert_datetime(year_i, month_i, day_i, time_val_extracted, am_pm_extracted, input_timezone_str="UTC", target_timezone_str="Asia/Shanghai")


def parse_launches_rocketlaunchlive(html_data):
    """
    解析来自 rocketlaunch.live 的HTML数据，返回发射信息列表。
    """
    soup = BeautifulSoup(html_data, 'html.parser')
    launches = []
    launch_entries = soup.find_all('div', class_='launch')
    for entry in launch_entries:
        datetime_div = entry.find('div', class_='launch_datetime')
        date_str = datetime_div.find('div', class_='launch_date').get_text(strip=True) if datetime_div else ''
        time_str = datetime_div.find('div', class_='launch_time').get_text(strip=True) if datetime_div else ''
        
        mission_name = entry.find('h4').get_text(strip=True) if entry.find('h4') else ''
        
        vehicle_div = entry.find('div', class_='rlt-vehicle')
        vehicle = vehicle_div.find('a').get_text(strip=True) if vehicle_div and vehicle_div.find('a') else ''
        
        location_div = entry.find('div', class_='rlt-location')
        location_parts = []
        raw_pad = "Unknown"
        if location_div:
            raw_pad = location_div.get_text(strip=True).split(',')[0].strip() # Original pad parsing
            location_parts.extend([a.get_text(strip=True) for a in location_div.find_all('a')])
            for string in location_div.stripped_strings:
                if string not in location_parts:
                    location_parts.append(string)
        full_location_str = ' '.join(location_parts) # This forms the location part
        
        launches.append({
            'date': date_str, 
            'time': time_str, 
            'mission': mission_name,
            'vehicle': vehicle,
            'pad': raw_pad, # Keep original pad for potential combination logic
            'location': full_location_str, # Keep original location
        })
    return launches

def _parse_datetime_nextspaceflight(datetime_str_gmt8: str) -> tuple[Optional[int], Optional[str]]:
    """
    Parses nextspaceflight.com's datetime string (e.g., "Sat May 10, 2025 08:00 GMT+8")
    Returns (ms_timestamp, iso_string_cst)
    """
    if not datetime_str_gmt8:
        return None, None

    # Remove " GMT+8" or other timezone abbreviations at the end
    datetime_str_cleaned = datetime_str_gmt8.replace(" GMT+8", "").strip()
    datetime_str_cleaned = re.sub(r'\s[A-Z]{3,}(?:[+-]\d{1,2})?$', '', datetime_str_cleaned).strip()
    
    # Define target timezone (Asia/Shanghai is GMT+8)
    cst_tz = ZoneInfo("Asia/Shanghai")

    try:
        # Attempt to parse format "Sat May 10, 2025 08:00"
        dt_naive = datetime.strptime(datetime_str_cleaned, "%a %b %d, %Y %H:%M")
    except ValueError:
        try:
            # Fallback: "May 10, 2025 08:00" (no day of week)
            dt_naive = datetime.strptime(datetime_str_cleaned, "%b %d, %Y %H:%M")
        except ValueError as e:
            logger.warning(f"NextSpaceflight datetime parsing failed for '{datetime_str_gmt8}' (cleaned: '{datetime_str_cleaned}'): {e}")
            return None, None
            
    # The parsed time is already meant to be GMT+8, so we make it aware with Asia/Shanghai
    dt_aware_cst = dt_naive.replace(tzinfo=cst_tz)
    
    timestamp_ms = int(dt_aware_cst.timestamp() * 1000)
    datetime_iso_str = dt_aware_cst.strftime("%Y-%m-%d %H:%M:%S %Z%z")

    if dt_aware_cst.year < 1970: # Should be rare for this source
        logger.info(f"NextSpaceflight date {dt_aware_cst.strftime('%Y-%m-%d')} is before 1970. Timestamp: {timestamp_ms} ms.")
        
    return timestamp_ms, datetime_iso_str

def _parse_launch_status_from_style(style_attribute: str | None) -> str:
    if not style_attribute:
        return "Unknown"
    match = re.search(r"border-color\s*:\s*([^;]+)", style_attribute, re.IGNORECASE)
    if not match:
        # logger.debug(f"Could not find border-color in style: '{style_attribute}'") # uncomment for debug
        return "Unknown"
    color_value = match.group(1).strip().lower()
    # logger.debug(f"Extracted border-color value: '{color_value}' from style: '{style_attribute}'") # uncomment for debug
    if color_value == "#45cf5d":
        return "Success"
    elif color_value == "#da3432":
        return "Failure"
    elif color_value == "#ff9900":
        return "Partial Success"
    elif color_value.startswith("rgba(255,255,255,"):
        return "Unknown" 
    else:
        # logger.debug(f"Unmatched border-color value: '{color_value}' (from style: '{style_attribute}')") # uncomment for debug
        return "Unknown"

def parse_launches_nextspaceflight(html_data: str, source_name: str):
    soup = BeautifulSoup(html_data, 'html.parser')
    launches = []
    launch_cards = soup.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split())

    for card in launch_cards:
        # ... (vehicle, mission, pad_location, provider parsing as before) ...
        header_style_tag = card.find('h5', class_='header-style') # Duplicated for context
        vehicle_mission_str = header_style_tag.get_text(strip=True) if header_style_tag else "Unknown | Unknown"
        parts = vehicle_mission_str.split('|', 1)
        vehicle = parts[0].strip()
        mission = parts[1].strip() if len(parts) > 1 else "N/A"

        datetime_span = card.find('span', id=re.compile(r'^localized\d+'))
        datetime_str_gmt8 = datetime_span.get_text(strip=True) if datetime_span else ""
        
        # Use the updated _parse_datetime_nextspaceflight
        timestamp_ms, datetime_str_iso = _parse_datetime_nextspaceflight(datetime_str_gmt8)

        # ... (pad_location_combined, status_en, mission_description, provider parsing as before) ...
        supporting_text_div = card.find('div', class_='mdl-card__supporting-text') # For context
        pad_location_combined = "Unknown" 
        if supporting_text_div:
            br_tag = supporting_text_div.find('br')
            if br_tag:
                content_after_br = [node.strip() for node in br_tag.find_next_siblings(string=True) if node.strip()]
                pad_location_combined = ', '.join(content_after_br) if content_after_br else "Unknown"
            # Fallback logic if needed...
        style_attr = card.get('style')
        status_en = _parse_launch_status_from_style(style_attr)
        mission_description = "N/A"
        provider_span = card.select_one('.mdl-card__title div.rcorners.a span')
        provider = provider_span.get_text(strip=True) if provider_span else "Unknown"


        launches.append({
            'mission': mission,
            'vehicle': vehicle,
            'pad_location': pad_location_combined,
            'timestamp_ms': timestamp_ms, # Store the millisecond timestamp (can be negative)
            'datetime_str': datetime_str_iso, # Store the ISO string representation
            'status': status_en,
            'mission_description': mission_description,
            'source_name': source_name,
            'provider': provider 
            # 'timestamp': timestamp_ms // 1000 if timestamp_ms is not None else None, # If you still need seconds timestamp for other logic
        })
    return launches