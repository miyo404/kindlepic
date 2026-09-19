"""
Kindle 新闻热榜壁纸生成器
复刻 DashWallpaper 内置看板排版：大标题+天气 / 黑底白字分组条 / 每条序号+加粗标题+右侧框 / 细横线 / 底部署名
数据源：tophub.today（微博热搜 / 知乎热榜 / 百度热搜）
天气：Open-Meteo 免费 API（苏州）
"""
from PIL import Image, ImageDraw, ImageFont
import requests
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
}
PROXIES = {'http': None, 'https': None}

# 三个新闻源：(分组名, tophub URL)
SOURCES = [
    ('微博热搜', 'https://tophub.today/n/KqndgxeLl9'),
    ('知乎热榜', 'https://tophub.today/n/mproPpoq6O'),
    ('百度热搜', 'https://tophub.today/n/Jb0vmloB1G'),
]

# 苏州坐标（Open-Meteo）
SUZHOU = (31.30, 120.62)

# WMO 天气码 → 中文
WEATHER_MAP = {
    0: '晴', 1: '晴', 2: '多云', 3: '阴',
    45: '雾', 48: '雾',
    51: '毛毛雨', 53: '毛毛雨', 55: '毛毛雨',
    61: '小雨', 63: '中雨', 65: '大雨',
    66: '冻雨', 67: '冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
    80: '阵雨', 81: '阵雨', 82: '暴雨',
    85: '阵雪', 86: '阵雪',
    95: '雷阵雨', 96: '雷阵雨', 99: '雷阵雨',
}


def fetch_top10(url):
    """抓 tophub 榜单前 10 条，返回 [(标题, 右侧热度值或''), ...]
    不同榜的 HTML 列结构不同：微博/百度是 [排名,标题,热度,图标]，知乎是 [排名,空,标题,图标]
    """
    try:
        r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        items = []
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2:
                continue
            # 找第一个含 <a> 的 cell 作为标题
            title = ''
            heat = ''
            for ci, c in enumerate(cells):
                a = c.find('a')
                if a and a.text.strip() and not title:
                    title = a.text.strip()
                    # 下一个非空 cell 可能是热度
                    if ci + 1 < len(cells):
                        nxt = cells[ci + 1].text.strip()
                        if nxt and any(ch.isdigit() for ch in nxt) and len(nxt) < 15:
                            heat = nxt
                    break
            if title:
                items.append((title, heat))
            if len(items) >= 10:
                break
        return items
    except Exception as e:
        print(f'[WARN] 抓取失败 {url}: {e}')
        return []


def fetch_weather():
    """返回 (城市, 天气描述, 当前温度, 最低温, 最高温)"""
    try:
        lat, lon = SUZHOU
        url = (f'https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}'
               f'&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min'
               f'&timezone=Asia/Shanghai&forecast_days=1')
        r = requests.get(url, timeout=10, proxies=PROXIES)
        r.raise_for_status()
        d = r.json()
        code = d['current']['weather_code']
        cur = round(d['current']['temperature_2m'])
        tmax = round(d['daily']['temperature_2m_max'][0])
        tmin = round(d['daily']['temperature_2m_min'][0])
        desc = WEATHER_MAP.get(code, '')
        return ('苏州', desc, cur, tmin, tmax)
    except Exception as e:
        print(f'[WARN] 天气获取失败: {e}')
        return ('苏州', '', '--', '--', '--')


# ---------- 字体 ----------
def load_fonts():
    # Linux（GitHub Actions）优先 Noto CJK；Windows 回退微软雅黑
    candidates_bold = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc',
        'C:/Windows/Fonts/msyhbd.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    candidates_regular = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    def pick(cands, size):
        for p in cands:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()
    return {
        'title':   pick(candidates_bold, 50),
        'group':   pick(candidates_bold, 28),
        'item':    pick(candidates_bold, 24),
        'side':    pick(candidates_bold, 20),
        'sub':     pick(candidates_regular, 22),
        'small':   pick(candidates_regular, 20),
        'tiny':    pick(candidates_regular, 18),
    }


def truncate(text, font, max_width, draw):
    """文字太长时截断加省略号"""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + '…', font=font) > max_width:
        text = text[:-1]
    return text + '…'


def render(groups, weather, output='pic/richang.png'):
    W, H = 1072, 1448
    MARGIN = 40
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    GRAY = (130, 130, 130)

    img = Image.new('RGB', (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f = load_fonts()

    city, desc, cur, tmin, tmax = weather
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # ===== 顶部标题区 =====
    y = 30
    d.text((MARGIN, y), '每日新闻热榜', fill=BLACK, font=f['title'])
    # 右上角天气
    wx_text = f'{city} · {desc} · {cur}°  {tmin}~{tmax}°'
    wx_w = d.textlength(wx_text, font=f['small'])
    d.text((W - MARGIN - wx_w, y + 18), wx_text, fill=BLACK, font=f['small'])

    # 副标题
    y += 64
    sub_text = '微博 / 知乎 / 百度  TOP10'
    d.text((MARGIN, y), sub_text, fill=GRAY, font=f['sub'])

    # 粗分隔线
    y += 34
    d.rectangle([MARGIN, y, W - MARGIN, y + 3], fill=BLACK)
    y += 14

    # ===== 分组区 =====
    right_box_w = 90
    right_box_h = 28
    item_gap = 36  # 每条行高
    header_h = 38  # 分组条高

    for gi, (group_name, items) in enumerate(groups):
        if not items:
            continue
        # 分组黑底条
        d.rectangle([MARGIN, y, W - MARGIN, y + header_h], fill=BLACK)
        d.text((MARGIN + 16, y + 6), group_name, fill=WHITE, font=f['group'])
        # 右侧条数
        cnt = str(len(items))
        cnt_w = d.textlength(cnt, font=f['group'])
        d.text((W - MARGIN - 16 - cnt_w, y + 6), cnt, fill=WHITE, font=f['group'])
        y += header_h + 4

        # 每条
        max_text_w = W - MARGIN * 2 - 50 - right_box_w - 30
        for i, (title, heat) in enumerate(items[:10], 1):
            rank = f'{i:02d}'
            # 灰色序号
            d.text((MARGIN, y + 6), rank, fill=GRAY, font=f['tiny'])
            # 加粗标题（截断）
            title = truncate(title, f['item'], max_text_w, d)
            d.text((MARGIN + 42, y + 4), title, fill=BLACK, font=f['item'])
            # 右侧框：放热度值（微博/百度有，知乎没有就空着）
            box_x1 = W - MARGIN - right_box_w
            box_y1 = y + 4
            if heat:
                d.rectangle([box_x1, box_y1, box_x1 + right_box_w, box_y1 + right_box_h],
                            outline=BLACK, width=1)
                hw = d.textlength(heat, font=f['side'])
                d.text((box_x1 + (right_box_w - hw) / 2, box_y1 + 4), heat,
                       fill=BLACK, font=f['side'])
            # 细横线
            d.line([MARGIN, y + item_gap, W - MARGIN, y + item_gap],
                   fill=(210, 210, 210), width=1)
            y += item_gap

        y += 12  # 组间距

    # ===== 底部署名 =====
    foot = f'看板休眠壁纸  ·  生成于 {now}'
    d.text((MARGIN, H - 36), foot, fill=GRAY, font=f['small'])

    img.save(output)
    print(f'图片已保存: {output}  尺寸={W}x{H}')


def main():
    groups = []
    for name, url in SOURCES:
        titles = fetch_top10(url)
        print(f'  {name}: {len(titles)} 条')
        groups.append((name, titles))
    weather = fetch_weather()
    print(f'  天气: {weather}')
    render(groups, weather, 'pic/richang.png')


if __name__ == '__main__':
    main()
