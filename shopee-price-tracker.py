import urllib.request
import urllib.parse
import json
import re
import ssl
import sys
import time

# --- การตั้งค่า (Configuration) ---
DISCORD_WEBHOOK_URL = "your_discord_webhook"
USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'

def log(msg):
    print(msg, flush=True)

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def extract_ids_from_url(url):
    """ดึง shop_id และ item_id จาก URL ของ Shopee"""
    # รูปแบบ: i.SHOPID.ITEMID
    match = re.search(r'i\.(\d+)\.(\d+)', url)
    if match:
        shop_id = match.group(1)
        item_id = match.group(2)
        return shop_id, item_id
    return None, None

def check_shopee_price(url):
    log(f"\n[Shopee] กำลังตรวจสอบ: {url[:80]}...")

    shop_id, item_id = extract_ids_from_url(url)
    if not shop_id or not item_id:
        log("❌ ไม่สามารถดึง shop_id / item_id จาก URL ได้")
        return None

    log(f"   > shop_id={shop_id}, item_id={item_id}")

    api_url = (
        f"https://shopee.co.th/api/v4/item/get"
        f"?itemid={item_id}&shopid={shop_id}"
    )

    headers = {
        'User-Agent': USER_AGENT,
        'Referer': 'https://shopee.co.th/',
        'Accept': 'application/json',
        'Accept-Language': 'th-TH,th;q=0.9,en;q=0.8',
        'X-API-SOURCE': 'pc',
        'X-Requested-With': 'XMLHttpRequest',
        'If-None-Match-': '',
    }

    ctx = ssl.create_default_context()

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read().decode('utf-8')
        data = json.loads(raw)
    except Exception as e:
        log(f"❌ API Error: {e}")
        return None

    item = data.get('data', {}) or data.get('item', {})
    if not item:
        log(f"❌ API ไม่คืนข้อมูลสินค้า (response: {raw[:200]})")
        return None

    title = item.get('name', 'ไม่พบชื่อสินค้า')

    # ราคา: Shopee เก็บเป็น satang (หาร 100000)
    price_min = item.get('price_min') or item.get('price')
    price_max = item.get('price_max') or item.get('price')

    def fmt_price(p):
        if p is None:
            return 'ไม่พบ'
        return f"{p / 100000:,.0f}"

    if price_min and price_max and price_min != price_max:
        price_str = f"{fmt_price(price_min)} - {fmt_price(price_max)}"
    else:
        price_str = fmt_price(price_min)

    # ราคาลด (ถ้ามี)
    price_before = item.get('price_before_discount')
    if price_before and price_before > 0 and price_before != price_min:
        price_str += f" ~~{fmt_price(price_before)}~~"

    stock = item.get('stock', 'N/A')
    rating = item.get('item_rating', {}).get('rating_star', 0)
    sold = item.get('historical_sold', 0)

    log(f"✅ {title}")
    log(f"   ราคา: {price_str} บาท | สต็อก: {stock} | ขายแล้ว: {sold} | ดาว: {rating:.1f}")

    return {
        "title": title,
        "price": price_str,
        "price_before": fmt_price(price_before) if price_before and price_before > 0 and price_before != price_min else None,
        "stock": stock,
        "sold": sold,
        "rating": rating,
        "url": url,
    }

def send_to_discord(product_data_list):
    log("\n--- กำลังส่งข้อมูลไป Discord ---")
    embeds = []
    for item in product_data_list:
        desc_lines = [f"💰 ราคา: **{item['price']} บาท**"]
        if item.get('price_before'):
            desc_lines.append(f"~~ราคาเดิม: {item['price_before']} บาท~~")
        desc_lines.append(f"📦 สต็อก: {item['stock']}")
        desc_lines.append(f"🛒 ขายแล้ว: {item['sold']}")
        desc_lines.append(f"⭐ {item['rating']:.1f}")

        embeds.append({
            "title": item["title"][:256],
            "url": item["url"],
            "description": "\n".join(desc_lines),
            "color": 15844367,  # สีส้ม Shopee
            "footer": {"text": "Shopee Price Monitor"}
        })

    payload = {
        "content": "📊 **รายงานอัปเดตราคา Shopee**",
        "embeds": embeds
    }
    data = json.dumps(payload).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT
    }

    req = urllib.request.Request(DISCORD_WEBHOOK_URL, data=data, headers=headers)
    try:
        urllib.request.urlopen(req, timeout=10)
        log("✅ ส่ง Discord สำเร็จ!")
    except Exception as e:
        log(f"❌ ส่ง Discord ล้มเหลว: {e}")

if __name__ == "__main__":
    shopee_urls = [
        "your_url",
        # เพิ่ม URL อื่นๆ ที่นี่
    ]

    collected_data = []

    for u in shopee_urls:
        res = check_shopee_price(u)
        if res:
            collected_data.append(res)
        time.sleep(2)

    if collected_data:
        send_to_discord(collected_data)
    else:
        log("\n⚠️ ไม่มีข้อมูลที่จะส่ง")

    log("\n=== ทำงานเสร็จสิ้น ===")
    input("กด Enter เพื่อปิด...")