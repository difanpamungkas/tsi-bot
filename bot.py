import os
import asyncio
import logging
import datetime
import json
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Token Bot Telegram Baru
TOKEN = "8839466878:AAGDgqk3bcKkjo4FCg4RV28qLgFXv3zTwyk"
BASE_URL = "https://tsiraw.tsindustri.com"

SLOC_KEYWORDS = ['GFGD', 'GFGL', 'PROD', 'DALAM', 'LUAR', 'PRODUKSI']

def is_sloc_name(val: str) -> bool:
    if not val:
        return False
    clean = val.upper().strip()
    return any(k in clean for k in SLOC_KEYWORDS)

def normalize_sloc(val: str) -> str:
    if not val:
        return 'GFGD'
    clean = str(val).upper().strip()
    if 'DALAM' in clean or clean == 'GFGD':
        return 'GFGD'
    if 'LUAR' in clean or clean == 'GFGL':
        return 'GFGL'
    if 'PRODUKSI' in clean or 'PROD' in clean:
        return 'PROD'
    return clean

async def process_tsi(roll_data: str) -> str:
    lines = [line.strip() for line in roll_data.strip().split('\n') if line.strip()]
    if not lines:
        return "⚠️ Tidak ada data roll yang valid."

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        results = []
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        try:
            await page.goto(f"{BASE_URL}/brctsloc", wait_until="networkidle")

            for line in lines:
                parts = [p.strip() for p in line.split(',') if p.strip()]
                if not parts:
                    continue

                batch_code = parts[0].upper()
                
                sender_sloc = None
                receiver_sloc = None
                clean_bin = ""

                if len(parts) >= 4:
                    sender_sloc = normalize_sloc(parts[1])
                    receiver_sloc = normalize_sloc(parts[2])
                    clean_bin = parts[3].upper()
                elif len(parts) == 3:
                    if is_sloc_name(parts[1]) and is_sloc_name(parts[2]):
                        sender_sloc = normalize_sloc(parts[1])
                        receiver_sloc = normalize_sloc(parts[2])
                    else:
                        receiver_sloc = normalize_sloc(parts[1])
                        clean_bin = parts[2].upper()
                elif len(parts) == 2:
                    receiver_sloc = normalize_sloc(parts[1])

                if not sender_sloc:
                    current_sloc = "GFGD"
                    stock_res = await page.request.post(
                        f"{BASE_URL}/rstock/get_stock",
                        form={
                            "mat": "",
                            "sloc": "",
                            "batch": batch_code,
                            "cust": "",
                            "refr": "",
                            "shift": ""
                        },
                        headers={"X-Requested-With": "XMLHttpRequest"}
                    )
                    if stock_res.ok:
                        try:
                            stock_json = await stock_res.json()
                            if isinstance(stock_json, list) and len(stock_json) > 0:
                                item = stock_json[0]
                                current_sloc = item.get("SLOC", "GFGD")
                                if not clean_bin:
                                    b_val = str(item.get("CODE_BIN") or item.get("BIN") or "").strip()
                                    if b_val.upper() not in ["NONE", "NULL", "NAN", "-", ""]:
                                        clean_bin = b_val.upper()
                        except Exception:
                            pass
                    sender_sloc = normalize_sloc(current_sloc)

                if not receiver_sloc:
                    receiver_sloc = "GFGL" if sender_sloc == "GFGD" else "GFGD"

                post_payload = {
                    "batch": batch_code,
                    "slocs": sender_sloc,
                    "slocr": receiver_sloc,
                    "datscan": today_str,
                    "bin": clean_bin,
                    "note": ""
                }

                headers = {
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest"
                }

                await page.request.post(
                    f"{BASE_URL}/ttranslist/save_scan",
                    form=post_payload,
                    headers=headers
                )

                post_res = await page.request.post(
                    f"{BASE_URL}/ttranslist/save_post",
                    form=post_payload,
                    headers=headers
                )

                if post_res.ok:
                    try:
                        res_json = await post_res.json()
                        msg = str(res_json.get("message", "")).lower()
                        if "berhasil" in msg or "ok" in msg or res_json.get("status") is True:
                            bin_info = f" (Bin: `{clean_bin}`)" if clean_bin else ""
                            results.append(f"✅ `{batch_code}`: {sender_sloc} ➔ {receiver_sloc}{bin_info}")
                        else:
                            err_msg = res_json.get("message") or "Ditolak server TSI"
                            results.append(f"❌ `{batch_code}`: {err_msg}")
                    except Exception:
                        results.append(f"✅ `{batch_code}`: {sender_sloc} ➔ {receiver_sloc}")
                else:
                    results.append(f"❌ `{batch_code}`: HTTP Error {post_res.status}")

                await asyncio.sleep(0.5)

            await browser.close()
            return "📊 **Hasil Pemindahan Sloc:**\n\n" + "\n".join(results)

        except Exception as e:
            await browser.close()
            return f"❌ Terjadi kesalahan di VPS: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **Bot TSI Raw Workstation Active!**\n\n"
        "Kirim daftar roll untuk memindahkan Sloc.\n\n"
        "**Format Pesan:**\n"
        "• `KODE_ROLL` (Auto Swap Sloc)\n"
        "• `KODE_ROLL, TARGET_SLOC` (Contoh: `GI123, GFGL`)\n"
        "• `KODE_ROLL, SLOC_ASAL, SLOC_TUJUAN` (Contoh: `GI123, GFGL, GFGD`)\n"
        "• `KODE_ROLL, SLOC_ASAL, SLOC_TUJUAN, BIN` (Contoh: `GI123, GFGL, GFGD, A01-02`)"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return
    
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    status_msg = await update.message.reply_text(f"⏳ Memproses {len(lines)} roll ke server TSI Raw...")
    
    result = await process_tsi(text)
    await status_msg.edit_text(result, parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("⚠️ Silakan upload file dengan format `.txt`!")
        return
        
    status_msg = await update.message.reply_text("⏳ Mengunduh file & memproses pemindahan Sloc...")
    
    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    content = file_bytes.decode('utf-8')
    
    result = await process_tsi(content)
    await status_msg.edit_text(result, parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot Telegram TSI Raw berjalan di VPS...")
    app.run_polling()

if __name__ == "__main__":
    main()
