from bs4 import BeautifulSoup, Tag
import re
from datetime import datetime
from zoneinfo import ZoneInfo # Using ZoneInfo
import logging

logger = logging.getLogger(__name__)

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

def _parse_datetime_nextspaceflight(datetime_str_gmt8: str) -> int | None:
    """
    解析 nextspaceflight.com 的日期时间字符串 (e.g., "Sat May 10, 2025 08:00 GMT+8")
    返回 UTC+8 的 Unix 时间戳 (秒).
    """
    if not datetime_str_gmt8:
        return None
    
    datetime_str = datetime_str_gmt8.replace(" GMT+8", "").strip()
    datetime_str = re.sub(r'\s[A-Z]{3,}(?:[+-]\d{1,2})?$', '', datetime_str).strip()

    try:
        dt_naive = datetime.strptime(datetime_str, "%a %b %d, %Y %H:%M")
        dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return int(dt_aware.timestamp())
    except ValueError as e:
        logger.debug(f"Failed to parse datetime string from NextSpaceflight: '{datetime_str_gmt8}' -> '{datetime_str}'. Error: {e}")
        try:
            dt_naive = datetime.strptime(datetime_str, "%b %d, %Y %H:%M")
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return int(dt_aware.timestamp())
        except ValueError:
            logger.warning(f"Failed to parse datetime string with alternative format: '{datetime_str}'. Error: {e}")
            return None

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
    """
    解析来自 nextspaceflight.com 的HTML数据，返回发射信息列表。
    """
    soup = BeautifulSoup(html_data, 'html.parser')
    launches = []
    launch_cards = soup.find_all('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split())

    for card in launch_cards:
        header_style_tag = card.find('h5', class_='header-style')
        vehicle_mission_str = header_style_tag.get_text(strip=True) if header_style_tag else "Unknown | Unknown"
        parts = vehicle_mission_str.split('|', 1)
        vehicle = parts[0].strip()
        mission = parts[1].strip() if len(parts) > 1 else "N/A"

        datetime_span = card.find('span', id=re.compile(r'^localized\d+'))
        datetime_str_gmt8 = datetime_span.get_text(strip=True) if datetime_span else ""
        timestamp = _parse_datetime_nextspaceflight(datetime_str_gmt8)

        supporting_text_div = card.find('div', class_='mdl-card__supporting-text')
        pad_location_combined = "Unknown" # This will be the combined field
        if supporting_text_div:
            br_tag = supporting_text_div.find('br')
            if br_tag:
                # Extract text after <br>
                content_after_br = []
                current_node = br_tag.next_sibling
                while current_node:
                    if isinstance(current_node, Tag):
                        content_after_br.append(current_node.get_text(strip=True))
                    elif isinstance(current_node, str): # NavigableString
                        stripped_str = current_node.strip()
                        if stripped_str:
                            content_after_br.append(stripped_str)
                    current_node = current_node.next_sibling
                pad_location_combined = ', '.join(filter(None, content_after_br)).strip().lstrip(',').strip()

            if not pad_location_combined or pad_location_combined == "Unknown": # Fallback if <br> parsing fails or yields nothing
                full_text = supporting_text_div.get_text(separator=' ', strip=True)
                if datetime_str_gmt8 and datetime_str_gmt8 in full_text:
                     # Attempt to remove the datetime part to get location
                    pad_location_combined = full_text.replace(datetime_str_gmt8, "").strip().lstrip(',').strip()
                elif full_text: # If datetime not found, use the whole text (less ideal)
                    pad_location_combined = full_text
        
        style_attr = card.get('style')
        status_en = _parse_launch_status_from_style(style_attr)

        mission_description = "N/A" # As per requirement, no direct field in list view

        provider_span = card.select_one('.mdl-card__title div.rcorners.a span')
        provider = provider_span.get_text(strip=True) if provider_span else "Unknown"

        launches.append({
            'mission': mission,
            'vehicle': vehicle,
            'pad_location': pad_location_combined, # New combined field
            'timestamp': timestamp or 0,
            'status': status_en,
            'mission_description': mission_description,
            'source_name': source_name,
            'provider': provider 
        })
    return launches