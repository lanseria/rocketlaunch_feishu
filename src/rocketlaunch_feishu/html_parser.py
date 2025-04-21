from bs4 import BeautifulSoup

def parse_launches(html_data):
    """
    解析HTML数据，返回发射信息列表。
    """
    soup = BeautifulSoup(html_data, 'html.parser')
    launches = []
    launch_entries = soup.find_all('div', class_='launch')
    for entry in launch_entries:
        # 提取发射日期和时间
        datetime_div = entry.find('div', class_='launch_datetime')
        date = datetime_div.find('div', class_='launch_date').get_text(strip=True) if datetime_div else ''
        time = datetime_div.find('div', class_='launch_time').get_text(strip=True) if datetime_div else ''
        # 提取任务名称
        mission_name = entry.find('h4').get_text(strip=True) if entry.find('h4') else ''
        # 提取火箭信息
        vehicle_div = entry.find('div', class_='rlt-vehicle')
        vehicle = vehicle_div.find('a').get_text(strip=True) if vehicle_div and vehicle_div.find('a') else ''
        # 提取发射地点信息
        location_div = entry.find('div', class_='rlt-location')
        location_parts = []
        if location_div:
            # 获取所有 a 标签文本
            location_parts.extend([a.get_text(strip=True) for a in location_div.find_all('a')])
            # 获取 location_div 下的直接文本（不在 a 标签内的文本）
            for string in location_div.stripped_strings:
                if string not in location_parts:
                    location_parts.append(string)
        location = ' '.join(location_parts)
        # 提取发射位（如果有）
        pad = location_div.get_text(strip=True).split(',')[0] if location_div else 'Unknown'
        launches.append({
            'date': date,
            'time': time,
            'mission': mission_name,
            'vehicle': vehicle,
            'pad': pad,
            'location': location
        })
    return launches
