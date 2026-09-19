"""
Kindle 新闻聚合器
- 读 sources.txt
- rss 源：解析 RSS/Atom，生成 feeds/<名称>.xml（新闻下载器订阅读全文）
- html 源（tophub）：抓榜单标题
- 所有源标题：生成 pic/richang.png 壁纸
"""
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont
import glob

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
PROXIES = {'http': None, 'https': None}
SOURCES_FILE = 'sources.txt'
FEEDS_DIR = 'feeds'
PIC_PATH = 'pic/richang.png'


# ---------- 读配置 ----------
def load_sources(path):
    sources = []
    if not os.path.exists(path):
        print(f'[ERR] 找不到 {path}')
        return sources
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            stype, name, url, limit = parts[0], parts[1], parts[2], parts[3]
            # 第5列：是否抓正文（1=抓），没有则默认不抓
            fetch_content = (len(parts) > 4 and parts[4].strip() == '1')
            try:
                limit = int(limit)
            except Exception:
                limit = 10
            sources.append((stype, name, url, limit, fetch_content))
    return sources


# ---------- 抓 RSS ----------
def fetch_rss(url, limit):
    """用标准库 xml.etree 解析 RSS 2.0 / Atom，返回 [(title, link, description), ...]"""
    try:
        r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        # RSS 2.0: <item>
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            desc = (item.findtext('description') or '').strip()
            if title:
                items.append((title, link, desc))
            if len(items) >= limit:
                break
        # Atom: <entry>
        if not items:
            for entry in root.iter('entry'):
                title = (entry.findtext('title') or '').strip()
                link = ''
                le = entry.find('link')
                if le is not None:
                    link = le.get('href', '')
                desc = (entry.findtext('summary') or entry.findtext('content') or '').strip()
                if title:
                    items.append((title, link, desc))
                if len(items) >= limit:
                    break
        return items
    except Exception as e:
        print(f'[WARN] RSS 抓取失败 {url}: {e}')
        return []


# ---------- 抓 tophub ----------
def fetch_tophub(url, limit):
    """抓 tophub 榜单，返回 [(title, link), ...]"""
    try:
        r = requests.get(url, headers=HEADERS, proxies=PROXIES, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        items = []
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 2:
                continue
            title = ''
            link = ''
            for c in cells:
                a = c.find('a')
                if a and a.text.strip() and not title:
                    title = a.text.strip()
                    link = a.get('href', '')
                    if link and link.startswith('/'):
                        link = 'https://tophub.today' + link
                    break
            if title:
                items.append((title, link))
            if len(items) >= limit:
                break
        return items
    except Exception as e:
        print(f'[WARN] tophub 抓取失败 {url}: {e}')
        return []


# ---------- 抓文章正文 ----------
def fetch_article_text(url):
    """访问文章URL，提取正文纯文本。抓不到返回空字符串。
    策略：先试常见正文容器选择器，失败再取body里最长的几段。"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        # 去掉导航/广告/脚本等无关标签
        for t in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            t.decompose()
        # 常见正文容器，挨个试
        for sel in ['article', '.article-content', '.news_txt', '#articleContent',
                    '.article-content-wrap', '.content', '.article_content', '.entry-content',
                    '.show_text', '.u-area']:
            el = soup.select_one(sel)
            if el:
                text = el.get_text('\n', strip=True)
                if len(text) > 150:
                    return text[:4000]
        # fallback：取body里最长的文本块
        if soup.body:
            text = soup.body.get_text('\n', strip=True)
            blocks = [b for b in text.split('\n') if len(b) > 100]
            if blocks:
                blocks.sort(key=len, reverse=True)
                return '\n'.join(blocks[:8])[:4000]
        return ''
    except Exception as e:
        print(f'    [WARN] 正文抓取失败 {url}: {e}')
        return ''


# ---------- 生成 RSS XML ----------
def build_rss_xml(name, items, source_url):
    # 生成标准 RSS 2.0。两点修复：
    # 1) description 不能留空自闭合(<description/>)，部分阅读器解析出错，空就填占位文字
    # 2) 补 pubDate 日期字段，更规范
    now = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')
    rss = ET.Element('rss')
    rss.set('version', '2.0')
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = name
    ET.SubElement(channel, 'link').text = source_url
    ET.SubElement(channel, 'description').text = f'{name} 聚合源'
    ET.SubElement(channel, 'pubDate').text = now
    for title, link, desc in items:
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = title
        ET.SubElement(item, 'link').text = link
        ET.SubElement(item, 'description').text = (desc or '（今日热榜条目，点开链接查看原文）')
        ET.SubElement(item, 'pubDate').text = now
    return ET.tostring(rss, encoding='utf-8', xml_declaration=True).decode('utf-8')


# ---------- 字体 ----------
def load_fonts():
    win_bold = r'C:\Windows\Fonts\msyhbd.ttc'
    win_reg = r'C:\Windows\Fonts\msyh.ttc'
    if os.path.exists(win_bold) and os.path.exists(win_reg):
        bold, regular = win_bold, win_reg
    else:
        cands = []
        for p in ['/usr/share/fonts/**/NotoSansCJK*.ttc', '/usr/share/fonts/**/NotoSansCJK*.otf']:
            cands.extend(glob.glob(p, recursive=True))
        def weight(p):
            n = os.path.basename(p).lower()
            if 'black' in n: return 0
            if 'bold' in n: return 1
            if 'medium' in n: return 3
            return 4
        cands = sorted(set(cands), key=weight)
        bold = cands[0] if cands else None
        regular = cands[-1] if cands else None
    def pick(p, size):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            return ImageFont.load_default()
    return {
        'title': pick(bold, 50), 'group': pick(bold, 28),
        'item': pick(bold, 24), 'side': pick(bold, 20),
        'sub': pick(regular, 22), 'small': pick(regular, 20),
        'tiny': pick(regular, 18),
    }


def text_height(draw, text, font):
    b = draw.textbbox((0, 0), text, font=font)
    return b[3] - b[1]


def truncate(text, font, max_width, draw):
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + '…', font=font) > max_width:
        text = text[:-1]
    return text + '…'


# ---------- 画壁纸 ----------
def render_png(groups, output):
    W, H = 1072, 1448
    MARGIN = 40
    BLACK, WHITE, GRAY = (0, 0, 0), (255, 255, 255), (130, 130, 130)
    img = Image.new('RGB', (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f = load_fonts()

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    y = 30
    d.text((MARGIN, y), '每日新闻热榜', fill=BLACK, font=f['title'])
    dt_w = d.textlength(now, font=f['small'])
    d.text((W - MARGIN - dt_w, y + 22), now, fill=BLACK, font=f['small'])
    y += 64
    names = ' / '.join(g[0] for g in groups)
    d.text((MARGIN, y), names, fill=GRAY, font=f['sub'])
    y += 34
    d.rectangle([MARGIN, y, W - MARGIN, y + 3], fill=BLACK)
    y += 14

    right_box_w, right_box_h, item_gap, header_h = 90, 28, 36, 38
    for group_name, items in groups:
        if not items:
            continue
        d.rectangle([MARGIN, y, W - MARGIN, y + header_h], fill=BLACK)
        gh = text_height(d, group_name, f['group'])
        gty = y + (header_h - gh) // 2
        d.text((MARGIN + 16, gty), group_name, fill=WHITE, font=f['group'])
        cnt = str(len(items))
        cnt_w = d.textlength(cnt, font=f['group'])
        d.text((W - MARGIN - 16 - cnt_w, gty), cnt, fill=WHITE, font=f['group'])
        y += header_h + 4
        max_text_w = W - MARGIN * 2 - 50 - right_box_w - 30
        for i, item in enumerate(items[:10], 1):
            title = item[0]
            heat = item[1] if len(item) > 1 else ''
            d.text((MARGIN, y + 8), f'{i:02d}', fill=GRAY, font=f['tiny'])
            title = truncate(title, f['item'], max_text_w, d)
            d.text((MARGIN + 42, y + 5), title, fill=BLACK, font=f['item'])
            box_x1 = W - MARGIN - right_box_w
            box_y1 = y + 5
            if heat:
                d.rectangle([box_x1, box_y1, box_x1 + right_box_w, box_y1 + right_box_h],
                            outline=BLACK, width=1)
                hw = d.textlength(heat, font=f['side'])
                d.text((box_x1 + (right_box_w - hw) / 2, box_y1 + 5), heat,
                       fill=BLACK, font=f['side'])
            d.line([MARGIN, y + item_gap, W - MARGIN, y + item_gap],
                   fill=(210, 210, 210), width=1)
            y += item_gap
        y += 12
    foot = f'看板休眠壁纸  ·  生成于 {now}'
    d.text((MARGIN, H - 36), foot, fill=GRAY, font=f['small'])
    img.save(output)
    print(f'壁纸已保存: {output}')


# ---------- 主流程 ----------
def main():
    os.makedirs(FEEDS_DIR, exist_ok=True)
    os.makedirs('pic', exist_ok=True)
    sources = load_sources(SOURCES_FILE)
    print(f'共 {len(sources)} 个源')

    wallpaper_groups = []  # (名称, [(标题, 热度或''), ...])

    for stype, name, url, limit, fetch_content in sources:
        print(f'\n--- {name} ({stype}) ---')
        if stype == 'rss':
            items = fetch_rss(url, limit)
            print(f'  RSS: {len(items)} 条')
            if items:
                xml = build_rss_xml(name, items, url)
                xml_path = os.path.join(FEEDS_DIR, f'{name}.xml')
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(xml)
                print(f'  RSS XML 已保存: {xml_path}')
            wallpaper_groups.append((name, [(t, '') for t, l, d in items]))
        elif stype == 'html':
            items = fetch_tophub(url, limit)
            print(f'  tophub: {len(items)} 条')
            rss_items = []
            for title, link in items:
                desc = ''
                # 如果配置要抓正文，访问每条链接抓正文
                if fetch_content and link:
                    print(f'    抓正文: {title[:25]}...')
                    desc = fetch_article_text(link)
                    if not desc:
                        desc = '（正文抓取失败，点链接查看原文）'
                rss_items.append((title, link, desc))
            if rss_items:
                xml = build_rss_xml(name, rss_items, url)
                xml_path = os.path.join(FEEDS_DIR, f'{name}.xml')
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(xml)
                print(f'  RSS XML 已保存: {xml_path}')
            wallpaper_groups.append((name, [(t, '') for t, l in items]))
        else:
            print(f'  未知类型 {stype}，跳过')

    if wallpaper_groups:
        render_png(wallpaper_groups, PIC_PATH)
    print('\n全部完成')


if __name__ == '__main__':
    main()
