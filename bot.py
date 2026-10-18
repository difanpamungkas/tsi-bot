import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

# Logging untuk memantau aktivitas bot di PM2
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Masukkan Bot Token Telegram kamu di sini (atau via environment variable BOT_TOKEN)
TOKEN = os.getenv("BOT_TOKEN", "ISI_BOT_TOKEN_TELEGRAM_KAMU_DI_SINI")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **TSI Raw (Headless Browser) Active!**\n\n"
        "Kirim daftar roll dalam format pesan teks atau upload file `rolls.txt`.\n\n"
        "Contoh format pesan:\n"
        "`GG19ADS1Q009, GFGL, GFGD`\n"
        "`GG19ADS1Q010, GFGL, GFGD`"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def process_tsi(roll_data: str) -> str:
    """Fungsi eksekusi Headless Browser (Playwright) untuk TSI Raw"""
    async with async_playwright() as p:
        # Menjalankan Chromium dengan argumen wajib di VPS Linux
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
        page.set_default_timeout(60000)  # Timeout 60 detik agar tidak rentan freeze

        try:
            # === TEMPAT LOGIKA PROSES / USERSCRIPT TSI RAW ===
            # Contoh eksekusi halaman & transfer:
            # await page.goto("https://tsi-raw-website.com")
            # await page.evaluate(...) # Jalankan logika Userscript v12.0.6
            
            await asyncio.sleep(2)  # Simulasi proses pemindahan
            await browser.close()
            
            lines = [line.strip() for line in roll_data.strip().split('\n') if line.strip()]
            return f"✅ Berhasil memproses {len(lines)} roll menggunakan Headless Browser!"
            
        except Exception as e:
            await browser.close()
            return f"❌ Error saat memproses di VPS: {str(e)}"

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return
    
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    status_msg = await update.message.reply_text(f"⏳ Memproses {len(lines)} roll menggunakan Headless Browser...")
    
    result = await process_tsi(text)
    await status_msg.edit_text(result)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("⚠️ Silakan upload file dengan format `.txt`!")
        return
        
    status_msg = await update.message.reply_text("⏳ Mengunduh file & memproses roll...")
    
    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    content = file_bytes.decode('utf-8')
    
    result = await process_tsi(content)
    await status_msg.edit_text(result)

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot Telegram TSI Raw berjalan di VPS...")
    app.run_polling()

if __name__ == "__main__":
    main()
