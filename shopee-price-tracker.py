import json
import re
import sys
import time
import subprocess

def log(msg):
    print(msg, flush=True)

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

DISCORD_WEBHOOK_URL = "your_dis_webhook"

def extract_ids_from_url(url):
    match = re.search(r'i\.(\d+)\.(\d+)', url)
    if match:
        return match.group(1), match.group(2)
    return None, None

def fmt_price(p):
    if p is None or p == 0:
        return None
    return f"{p / 100000:,.0f}"

def check_shopee_price(url):
    log(f"\n[Shopee] กำลังตรวจสอบ...")
    shop_id, item_id = extract_ids_from_url(url)
    if not shop_id:
        log("❌ ไม่พบ shop_id/item_id ใน URL")
        return None
    log(f"   > shop_id={shop_id}, item_id={item_id}")

    from playwright.sync_api import sync_playwright

    captured = {}

    def handle_response(response):
        try:
            if response.status != 200:
                return
            url_r = response.url
            if 'item/get' in url_r or (f'itemid={item_id}' in url_r and f'shopid={shop_id}' in url_r):
                data = response.json()
                item = data.get('data') or data.get('item')
                if item and item.get('name'):
                    captured['item'] = item
        except:
            pass

    with sync_playwright() as p:
        log("   > เปิด browser (ไม่มีหน้าต่าง)")
        ctx = p.chromium.launch_persistent_context(
            user_data_dir="./shopee_profile",
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", handle_response)

        log(f"   > กำลังโหลดหน้าสินค้า...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except:
            pass

        for _ in range(15):
            if captured.get('item'):
                break
            time.sleep(1)

        if not captured.get('item'):
            log("   > ลองดึงจาก DOM...")
            try:
                page.wait_for_selector('div[class*="price"]', timeout=8000)
            except:
                pass
            time.sleep(2)
            title = page.title().replace(" | Shopee Thailand", "").strip()
            try:
                body = page.evaluate("document.body.innerText")
                m = re.search(r'฿\s*([\d,]+)', body)
                if m:
                    ctx.close()
                    log(f"✅ {title} | ราคา: {m.group(1)} บาท")
                    return {"title": title, "price": m.group(1), "price_before": None,
                            "stock": "N/A", "sold": 0, "rating": 0, "url": url}
            except:
                pass
            ctx.close()
            log("❌ ไม่พบราคา — ลองรัน login_shopee.py ใหม่")
            return None

        ctx.close()

    item = captured['item']
    title = item.get('name', 'ไม่พบชื่อ')
    price_min = item.get('price_min') or item.get('price')
    price_max = item.get('price_max') or item.get('price')
    price_before = item.get('price_before_discount')

    if price_min and price_max and price_min != price_max:
        price_str = f"{fmt_price(price_min)} - {fmt_price(price_max)}"
    else:
        price_str = fmt_price(price_min) or "ไม่พบ"

    stock = item.get('stock', 'N/A')
    sold = item.get('historical_sold', 0)
    rating = (item.get('item_rating') or {}).get('rating_star', 0)

    log(f"✅ {title}")
    log(f"   ราคา: {price_str} บาท | สต็อก: {stock} | ขายแล้ว: {sold} | ดาว: {rating:.1f}")

    return {
        "title": title,
        "price": price_str,
        "price_before": fmt_price(price_before) if price_before and price_before != price_min else None,
        "stock": stock, "sold": sold, "rating": rating, "url": url,
    }

def send_to_discord(product_data_list):
    log("\n--- กำลังส่งข้อมูลไป Discord ---")
    embeds = []
    for item in product_data_list:
        lines = [f"💰 ราคา: **{item['price']} บาท**"]
        if item.get('price_before'):
            lines.append(f"🏷️ ราคาเดิม: ~~{item['price_before']} บาท~~")
        lines.append(f"📦 สต็อก: {item['stock']}")
        lines.append(f"🛒 ขายแล้ว: {item['sold']}")
        if item['rating']:
            lines.append(f"⭐ คะแนน: {item['rating']:.1f}")
        embeds.append({
            "title": item["title"][:256],
            "url": item["url"],
            "description": "\n".join(lines),
            "color": 15844367,
            "footer": {"text": "Shopee Price Monitor"}
        })

    payload = {"content": "📊 **รายงานอัปเดตราคา Shopee**", "embeds": embeds}
    payload_str = json.dumps(payload, ensure_ascii=False)

    # ใช้ curl แทน urllib เพื่อหลีกเลี่ยง 403
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         "-X", "POST",
         "-H", "Content-Type: application/json",
         "-d", payload_str,
         DISCORD_WEBHOOK_URL],
        capture_output=True, text=True
    )
    code = result.stdout.strip()
    if code in ("200", "204"):
        log("✅ ส่ง Discord สำเร็จ!")
    else:
        log(f"❌ ส่ง Discord ล้มเหลว (HTTP {code})")
        log(f"   stderr: {result.stderr[:200]}")

if __name__ == "__main__":
    shopee_urls = [
        "your_shopee_url_1",
        "your_shopee_url_2",
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
