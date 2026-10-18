import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

# Server dummy untuk Render Web Service Free
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot TSI Raw Active!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Konfigurasi Bot & TSI Raw
TELEGRAM_BOT_TOKEN = "8839466878:AAETekpgfiY-V7eSttUUlVh8O3pF3youOCE"
USERNAME_TSI = "Ppic03"
PASSWORD_TSI = "gbj12345"
BASE_URL = "https://tsiraw.tsindustri.com"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Selamat datang di Bot Transfer TSI Raw (Headless Browser)!\n\n"
        "Kirim daftar roll dalam format pesan teks atau upload file `rolls.txt`.\n"
        "Contoh format pesan:\n"
        "`GG19ADS1Q009, GFGL, GFGD`\n"
        "`GG19ADS1Q010, GFGL, GFGD`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def process_text_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    await execute_transfers(update, lines)

async def process_file_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    file = await context.bot.get_file(document.file_id)
    file_bytes = await file.download_as_bytearray()
    lines = [line.strip() for line in file_bytes.decode("utf-8").split("\n") if line.strip()]
    await execute_transfers(update, lines)

async def execute_transfers(update: Update, lines: list):
    status_msg = await update.message.reply_text(f"⏳ Memproses {len(lines)} roll menggunakan Headless Browser...")
    today = datetime.now().strftime("%Y-%m-%d")
    log_results = []

    async with async_playwright() as p:
        # Jalankan Chromium headless di server
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # 1. Login via Browser Sungguhan
            await page.goto(f"{BASE_URL}/login", timeout=30000)
            await page.fill('input[name="username"]', USERNAME_TSI)
            await page.fill('input[name="password"]', PASSWORD_TSI)
            await page.click('button[type="submit"], input[type="submit"]')
            await page.wait_for_timeout(3000)

            # 2. Eksekusi transfer di dalam konteks browser yang tersesi
            for idx, line in enumerate(lines, 1):
                parts = [p.strip().upper() for p in line.split(",") if p.strip()]
                if not parts:
                    continue

                kode_roll = parts[0]
                sloc_asal = parts[1] if len(parts) > 1 else "GFGD"
                sloc_tujuan = parts[2] if len(parts) > 2 else "GFGL"
                bin_tujuan = parts[3] if len(parts) > 3 else ""

                # Kirim request transaksi langsung dari dalam konteks JS browser
                js_script = f"""
                    async () => {{
                        await fetch('{BASE_URL}/brctsloc');
                        
                        const payload = new URLSearchParams();
                        payload.append('batch', '{kode_roll}');
                        payload.append('slocs', '{sloc_asal}');
                        payload.append('slocr', '{sloc_tujuan}');
                        payload.append('datscan', '{today}');
                        payload.append('bin', '{bin_tujuan}');
                        payload.append('note', '');

                        await fetch('{BASE_URL}/ttranslist/save_scan', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' }},
                            body: payload
                        }});

                        const resPost = await fetch('{BASE_URL}/ttranslist/save_post', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' }},
                            body: payload
                        }});

                        return resPost.status;
                    }}
                """
                
                status_code = await page.evaluate(js_script)

                if status_code == 200:
                    log_results.append(f"✅ [{idx}/{len(lines)}] {kode_roll}: Sukses")
                else:
                    log_results.append(f"⚠️ [{idx}/{len(lines)}] {kode_roll}: Gagal HTTP {status_code}")

        except Exception as e:
            log_results.append(f"💥 Error Browser: {str(e)}")
        finally:
            await browser.close()

    final_report = "🎉 **Proses Pemindahan Selesai!**\n\n" + "\n".join(log_results)
    await status_msg.edit_text(final_report, parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_data))
    app.add_handler(MessageHandler(filters.Document.ALL, process_file_data))
    app.run_polling()
