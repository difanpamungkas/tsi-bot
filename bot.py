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

# KREDENSIAL AKUN TSI RAW
TSI_USERNAME = "Ppic06"
TSI_PASSWORD = "rio234"

SLOC_KEYWORDS = ['GFGD', 'GFGL', 'PROD', 'DALAM', 'LUAR', 'PRODUKSI']

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
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        results = []
        today_str = datetime.date.today().strftime("%Y-%m-%d")

        try:
            # 1. ALUR AUTO-LOGIN
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            
            user_input = page.locator("input[name*='user' i], input[name*='email' i], input[id*='user' i]").first
            pass_input = page.locator("input[type='password']").first
            
            if await user_input.count() > 0 and await pass_input.count() > 0:
                await user_input.fill(TSI_USERNAME)
                await pass_input.fill(TSI_PASSWORD)
                
                submit_btn = page.locator("button[type='submit'], input[type='submit'], .btn-primary").first
                if await submit_btn.count() > 0:
                    await submit_btn.click()
                    await page.wait_for_load_state("networkidle")

            # 2. Buka Halaman Transaksi
            await page.goto(f"{BASE_URL}/brctsloc", wait_until="networkidle")
            
            if "login" in page.url.lower():
                await browser.close()
                return "❌ **Gagal Login TSI Raw!** Periksa kombinasi Username/Password TSI."

            # 3. Eksekusi Roll
            for line in lines:
                parts = [p.strip() for p in line.split(',') if p.strip()]
                if not parts:
                    continue

                batch_code = parts[0].upper()
                sender_sloc = None
                receiver_sloc = None
                clean_bin = ""

                if len(parts) >= 3:
                    sender_sloc = normalize_sloc(parts[1])
                    receiver_sloc = normalize_sloc(parts[2])
                    if len(parts) >= 4:
                        clean_bin = parts[3].upper()
                elif len(parts) == 2:
                    receiver_sloc = normalize_sloc(parts[1])

                if not sender_sloc:
                    sender_sloc = "GFGD"
                    stock_res = await page.request.post(
                        f"{BASE_URL}/rstock/get_stock",
                        form={"mat": "", "sloc": "", "batch": batch_code, "cust": "", "refr": "", "shift": ""},
                        headers={"X-Requested-With": "XMLHttpRequest"}
                    )
                    if stock_res.ok:
                        try:
                            st_json = await stock_res.json()
                            if isinstance(st_json, list) and len(st_json) > 0:
                                sender_sloc = normalize_sloc(st_json[0].get("SLOC", "GFGD"))
                        except Exception:
                            pass

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

                # Exec API Save Scan & Save Post
                await page.request.post(f"{BASE_URL}/ttranslist/save_scan", form=post_payload, headers=headers)
                post_res = await page.request.post(f"{BASE_URL}/ttranslist/save_post", form=post_payload, headers=headers)

                res_text = await post_res.text()
                
                if post_res.ok:
                    try:
                        res_json = json.loads(res_text)
                        msg = str(res_json.get("message", res_text)).strip()
                        if "berhasil" in msg.lower() or "ok" in msg.lower() or res_json.get("status") is True:
                            results.append(f"✅ `{batch_code}`: {sender_sloc} ➔ {receiver_sloc}")
                        else:
                            results.append(f"❌ `{batch_code}`: `{msg}`")
                    except Exception:
                        results.append(f"⚠️ `{batch_code}`: Respon TSI: `{res_text[:100]}`")
                else:
                    results.append(f"❌ `{batch_code}`: HTTP Error {post_res.status}")

                await asyncio.sleep(0.5)

            await browser.close()
            return "📊 **Hasil Pemindahan Sloc:**\n\n" + "\n".join(results)

        except Exception as e:
            await browser.close()
            return f"❌ Terjadi kesalahan di VPS: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 **Bot TSI Raw Workstation Active!**\nKirim format: `KODE_ROLL, GFGL, GFGD`")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text:
        return
    status_msg = await update.message.reply_text("⏳ Memproses ke server TSI Raw...")
    result = await process_tsi(update.message.text)
    await status_msg.edit_text(result, parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("⚠️ Upload file `.txt`!")
        return
    status_msg = await update.message.reply_text("⏳ Memproses file...")
    file = await context.bot.get_file(doc.file_id)
    content = (await file.download_as_bytearray()).decode('utf-8')
    result = await process_tsi(content)
    await status_msg.edit_text(result, parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()

if __name__ == "__main__":
    main()
