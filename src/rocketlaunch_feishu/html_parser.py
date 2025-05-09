from bs4 import BeautifulSoup, Tag
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
from typing import Optional, Tuple # Corrected import for Tuple

logger = logging.getLogger(__name__)

# Removed: parse_and_convert_datetime (if only for rocketlaunch.live)
# Removed: parse_datetime_rocketlaunchlive_dict
# Removed: parse_launches_rocketlaunchlive

def _parse_datetime_nextspaceflight(datetime_str_gmt8: str) -> Tuple[Optional[int], Optional[str]]: # Use Tuple
    """
    Parses nextspaceflight.com's datetime string (e.g., "Sat May 10, 2025 08:00 GMT+8")
    Returns (ms_timestamp, iso_string_cst)
    """
    if not datetime_str_gmt8:
        return None, None

    datetime_str_cleaned = datetime_str_gmt8.replace(" GMT+8", "").strip()
    datetime_str_cleaned = re.sub(r'\s[A-Z]{3,}(?:[+-]\d{1,2})?$', '', datetime_str_cleaned).strip()
    
    cst_tz = ZoneInfo("Asia/Shanghai")

    try:
        dt_naive = datetime.strptime(datetime_str_cleaned, "%a %b %d, %Y %H:%M")
    except ValueError:
        try:
            dt_naive = datetime.strptime(datetime_str_cleaned, "%b %d, %Y %H:%M")
        except ValueError as e:
            logger.warning(f"NextSpaceflight datetime parsing failed for '{datetime_str_gmt8}' (cleaned: '{datetime_str_cleaned}'): {e}")
            return None, None
            
    dt_aware_cst = dt_naive.replace(tzinfo=cst_tz)
    
    timestamp_ms = int(dt_aware_cst.timestamp() * 1000)
    datetime_iso_str = dt_aware_cst.strftime("%Y-%m-%d %H:%M:%S %Z%z")

    if dt_aware_cst.year < 1970:
        logger.info(f"NextSpaceflight date {dt_aware_cst.strftime('%Y-%m-%d')} is before 1970. Timestamp: {timestamp_ms} ms.")
        
    return timestamp_ms, datetime_iso_str

def _parse_launch_status_from_style(style_attribute: str | None) -> str:
    if not style_attribute:
        return "Unknown"
    match = re.search(r"border-color\s*:\s*([^;]+)", style_attribute, re.IGNORECASE)
    if not match:
        return "Unknown"
    color_value = match.group(1).strip().lower()
    if color_value == "#45cf5d": return "Success"
    elif color_value == "#da3432": return "Failure"
    elif color_value == "#ff9900": return "Partial Success"
    elif color_value.startswith("rgba(255,255,255,"): return "Unknown" 
    else: return "Unknown"

def parse_launches_nextspaceflight(html_data: str, source_name: str): # source_name might become redundant if only one source
    soup = BeautifulSoup(html_data, 'html.parser')
    launches = []
    # Use a more specific selector if the class "launch" and "mdl-card" is too generic on the page
    launch_cards = soup.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split() and 'mdl-cell' not in x.split())


    for card in launch_cards:
        header_style_tag = card.find('h5', class_='header-style')
        vehicle_mission_str = header_style_tag.get_text(strip=True) if header_style_tag else "Unknown | Unknown"
        parts = vehicle_mission_str.split('|', 1)
        vehicle = parts[0].strip()
        mission = parts[1].strip() if len(parts) > 1 else "N/A"

        datetime_span = card.find('span', id=re.compile(r'^localized\d+'))
        datetime_str_gmt8 = datetime_span.get_text(strip=True) if datetime_span else ""
        timestamp_ms, datetime_str_iso = _parse_datetime_nextspaceflight(datetime_str_gmt8)

        supporting_text_div = card.find('div', class_='mdl-card__supporting-text')
        pad_location_combined = "Unknown" 
        if supporting_text_div:
            # More robust extraction of text after <br>
            br_tag = supporting_text_div.find('br')
            if br_tag:
                location_text_nodes = []
                sibling = br_tag.next_sibling
                while sibling:
                    if isinstance(sibling, str): # NavigableString
                        stripped_text = sibling.strip()
                        if stripped_text:
                            location_text_nodes.append(stripped_text)
                    elif isinstance(sibling, Tag): # If there are other tags after <br>
                        # Decide if to get their text, e.g. sibling.get_text(strip=True)
                        # For now, assuming simple text nodes after <br>
                        pass 
                    sibling = sibling.next_sibling
                pad_location_combined = ', '.join(location_text_nodes) if location_text_nodes else "Unknown"
            else: # No <br>, try to get all text and clean
                full_text = supporting_text_div.get_text(separator=' ', strip=True)
                if datetime_str_gmt8 and datetime_str_gmt8 in full_text:
                    pad_location_combined = full_text.replace(datetime_str_gmt8, "").strip().lstrip(',').strip()
                else:
                    pad_location_combined = full_text if full_text else "Unknown"
        
        style_attr = card.get('style')
        status_en = _parse_launch_status_from_style(style_attr)
        mission_description = "N/A" # No description in list view
        provider_span = card.select_one('.mdl-card__title div.rcorners.a span')
        provider = provider_span.get_text(strip=True) if provider_span else "Unknown"

        launches.append({
            'mission': mission, 'vehicle': vehicle, 'pad_location': pad_location_combined,
            'timestamp_ms': timestamp_ms, 'datetime_str': datetime_str_iso,
            'status': status_en, 'mission_description': mission_description,
            'source_name': source_name, 'provider': provider 
        })
    return launches