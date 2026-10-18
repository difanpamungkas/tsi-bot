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
            # 1. PROSES LOGIN KE WEB TSI
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

            # 2. MASUK KE HALAMAN SLOC
            await page.goto(f"{BASE_URL}/brctsloc", wait_until="networkidle")
            
            if "login" in page.url.lower():
                await browser.close()
                return "❌ **Gagal Login TSI Raw!** Username atau Password ditolak server."

            # 3. EKSEKUSI API DALAM KONTEKS BROWSER (NATIVE FETCH)
            js_fetch_script = """
            async ([batch, slocs, slocr, binCode, todayStr]) => {
                const postData = new URLSearchParams({
                    'batch': batch,
                    'slocs': slocs,
                    'slocr': slocr,
                    'datscan': todayStr,
                    'bin': binCode,
                    'note': ''
                });

                await fetch('/ttranslist/save_scan', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: postData
                });

                const resPost = await fetch('/ttranslist/save_post', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: postData
                });

                const text = await resPost.text();
                try {
                    return JSON.parse(text);
                } catch(e) {
                    return { status: false, message: text };
                }
            }
            """

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

                if not receiver_sloc:
                    receiver_sloc = "GFGL" if sender_sloc == "GFGD" else "GFGD"

                # Jalankan fetch langsung dari window browser yang sudah ter-login
                res_json = await page.evaluate(
                    js_fetch_script, 
                    [batch_code, sender_sloc, receiver_sloc, clean_bin, today_str]
                )

                msg = str(res_json.get("message", "")).strip()
                if "berhasil" in msg.lower() or "ok" in msg.lower() or res_json.get("status") is True:
                    bin_info = f" (Bin: `{clean_bin}`)" if clean_bin else ""
                    results.append(f"✅ `{batch_code}`: {sender_sloc} ➔ {receiver_sloc}{bin_info}")
                else:
                    results.append(f"❌ `{batch_code}`: `{msg[:120]}`")

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
