"""为无配图商品从国内图源下载相关图片"""
import os
import urllib.request
import urllib.parse
import urllib.error
import json
import re
import time
import ssl

os.environ["DJANGO_SETTINGS_MODULE"] = "product.settings"
import django
django.setup()
from user.models import Product

# 忽略 SSL 证书问题
ssl._create_default_https_context = ssl._create_unverified_context


def search_image_url_baidu(keyword):
    """从百度图片搜索获取第一张图片URL"""
    url = "https://image.baidu.com/search/acjson?tn=resultjson_com&word=" + urllib.parse.quote(keyword)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://image.baidu.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for item in data.get("data", []):
                if "thumbURL" in item and item["thumbURL"]:
                    return item["thumbURL"]
                if "middleURL" in item and item["middleURL"]:
                    return item["middleURL"]
    except Exception as e:
        print(f"    搜索失败: {e}")
    return None


def search_image_url_bing(keyword):
    """从 Bing 图片搜索获取第一张图片URL"""
    url = "https://cn.bing.com/images/search?q=" + urllib.parse.quote(keyword) + "&first=1"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode()
            # 匹配 Bing 图片搜索结果中的图片 URL
            urls = re.findall(r'murl&quot;:&quot;(https?://[^&]+?\.(?:jpg|jpeg|png))', html)
            if urls:
                return urls[0]
            # 另一种格式
            urls = re.findall(r'imgurl=([^&]+)', html)
            if urls:
                return urllib.parse.unquote(urls[0])
    except Exception as e:
        print(f"    Bing搜索失败: {e}")
    return None


def download_image(url, filepath):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.baidu.com/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            if len(data) < 500:
                return False
            with open(filepath, "wb") as f:
                f.write(data)
        return True
    except Exception as e:
        print(f"    下载失败: {e}")
        return False


def make_keyword(product):
    """提取核心搜索词"""
    name = product.name
    # 移除品牌名、年份、长度描述等干扰词
    for rm in ["2025新款", "2024新款", "2025早秋", "【女神礼物】", "官方正品",
               "IDEAGEMER ", "CLOSENSE『浮光』系列", "RC Retro Chic",
               "BJHG不计后果", "「GUIER」", "鹿向南「暮雪披风」",
               "梅子熟了【圣马丁】", "HS美式", "V37 ", "班尼路",
               "高端连帽", "官方正品王嘉尔同款",
               "灰色"]:
        name = name.replace(rm, "")
    # 再精简
    words = name.strip().split()
    kw = " ".join([w for w in words if len(w) > 1][:4])
    if not kw:
        kw = name[:20]
    return kw


def main():
    products = list(Product.objects.filter(pic="").order_by("id"))
    if not products:
        print("所有商品已有配图")
        return

    print(f"需要补图: {len(products)} 件\n")

    for i, p in enumerate(products):
        kw = make_keyword(p)
        filename = f"{p.id}.jpg"
        filepath = "d:/商品推荐系统/media/" + filename

        print(f"[{i+1}/{len(products)}] ID={p.id} | {kw}")

        # 依次尝试百度、Bing
        img_url = search_image_url_baidu(kw)
        if not img_url:
            print("    百度无结果，尝试Bing...")
            img_url = search_image_url_bing(kw)

        if img_url:
            print(f"    URL: {img_url[:80]}...")
            if download_image(img_url, filepath):
                p.pic = filename
                p.save()
                print(f"    ✓ 已保存 media/{filename}")
            else:
                img_url = None

        if not img_url:
            # 用 Pillow 生成占位图
            try:
                from PIL import Image, ImageDraw
            except ImportError:
                print(f"    ✗ 跳过")
                continue

            colors = ["#2B579A", "#E74856", "#0078D7", "#10893E", "#6B69D6",
                       "#DA3B01", "#8764B8", "#515C6B", "#4A5459"]
            color = colors[p.id % len(colors)]
            img = Image.new("RGB", (400, 400), color)
            draw = ImageDraw.Draw(img)
            draw.text((200, 180), kw[:18], fill="white", anchor="mm")
            draw.text((200, 220), f"ID: {p.id}", fill="#CCCCCC", anchor="mm")

            fname = f"{p.id}.png"
            img.save("d:/商品推荐系统/media/" + fname)
            p.pic = fname
            p.save()
            print(f"    → 占位图 media/{fname}")

        time.sleep(1.2)

    left = Product.objects.filter(pic="").count()
    print(f"\n完成! 剩余无图: {left} 件")


if __name__ == "__main__":
    main()
