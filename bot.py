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

TOKEN = "8839466878:AAGDgqk3bcKkjo4FCg4RV28qLgFXv3zTwyk"
BASE_URL = "https://tsiraw.tsindustri.com"

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
            # 1. Buka halaman utama untuk pembentukan session & cookies
            await page.goto(f"{BASE_URL}/brctsloc", wait_until="networkidle")

            for line in lines:
                parts = [p.strip() for p in line.split(',') if p.strip()]
                if not parts:
                    continue

                batch_code = parts[0].upper()
                target_sloc_input = parts[1] if len(parts) > 1 else None
                target_bin_input = parts[2] if len(parts) > 2 else ""

                # 2. Cek stok awal via API
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

                current_sloc = "GFGD"
                clean_bin = target_bin_input.upper()

                if stock_res.ok:
                    try:
                        stock_json = await stock_res.json()
                        if isinstance(stock_json, list) and len(stock_json) > 0:
                            item = stock_json[0]
                            current_sloc = item.get("SLOC", "GFGD")
                            if not clean_bin:
                                clean_bin = str(item.get("CODE_BIN") or item.get("BIN") or "").strip().upper()
                                if clean_bin in ["NONE", "NULL", "NAN", "-"]:
                                    clean_bin = ""
                    except Exception:
                        pass

                sender_sloc = normalize_sloc(current_sloc)

                # 3. Tentukan Sloc Receiver (Target)
                if target_sloc_input:
                    receiver_sloc = normalize_sloc(target_sloc_input)
                else:
                    # Auto Swap (Dalam <-> Luar)
                    if sender_sloc == "GFGD":
                        receiver_sloc = "GFGL"
                    elif sender_sloc == "GFGL":
                        receiver_sloc = "GFGD"
                    else:
                        receiver_sloc = "GFGD"

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

                # 4. Eksekusi API Save Scan
                scan_res = await page.request.post(
                    f"{BASE_URL}/ttranslist/save_scan",
                    form=post_payload,
                    headers=headers
                )

                # 5. Eksekusi API Save Post
                post_res = await page.request.post(
                    f"{BASE_URL}/ttranslist/save_post",
                    form=post_payload,
                    headers=headers
                )

                if post_res.ok:
                    results.append(f"✅ `{batch_code}`: {sender_sloc} ➔ {receiver_sloc}")
                else:
                    results.append(f"❌ `{batch_code}`: Gagal Posting")

                await asyncio.sleep(0.5)

            await browser.close()
            
            summary = "\n".join(results)
            return f"📊 **Hasil Pemindahan Sloc:**\n\n{summary}"

        except Exception as e:
            await browser.close()
            return f"❌ Terjadi kesalahan saat memproses di VPS: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **Bot TSI Raw Workstation Active!**\n\n"
        "Kirim daftar roll untuk langsung dipindahkan Sloc-nya.\n\n"
        "**Format Pesan:**\n"
        "`KODE_ROLL` (Auto Swap Sloc)\n"
        "`KODE_ROLL, TARGET_SLOC` (Contoh: `GI123, GFGL`)\n"
        "`KODE_ROLL, TARGET_SLOC, TARGET_BIN` (Contoh: `GI123, GFGL, A01-02`)"
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
