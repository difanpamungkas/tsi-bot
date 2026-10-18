import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# SERVER DUMMY UNTUK RENDER WEB SERVICE FREE
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot TSI Raw Active!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ==========================================
# KONFIGURASI BOT & TSI RAW
# ==========================================
TELEGRAM_BOT_TOKEN = "8839466878:AAETekpgfiY-V7eSttUUlVh8O3pF3youOCE"

BASE_URL = "https://tsiraw.tsindustri.com"
URL_LOGIN = f"{BASE_URL}/login/process"
URL_SESSION_INIT = f"{BASE_URL}/brctsloc"
URL_SAVE_SCAN = f"{BASE_URL}/ttranslist/save_scan"
URL_SAVE_POST = f"{BASE_URL}/ttranslist/save_post"

USERNAME_TSI = "Ppic03"
PASSWORD_TSI = "gbj12345"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
}

def do_tsi_login(session):
    payload = {"username": USERNAME_TSI, "password": PASSWORD_TSI}
    res = session.post(URL_LOGIN, data=payload, timeout=10)
    return res.status_code == 200

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Selamat datang di Bot Transfer TSI Raw!\n\n"
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
    status_msg = await update.message.reply_text(f"⏳ Memproses {len(lines)} roll...")
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    if not do_tsi_login(session):
        await status_msg.edit_text("❌ Gagal login ke server TSI Raw. Periksa akun!")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    log_results = []

    for idx, line in enumerate(lines, 1):
        parts = [p.strip().upper() for p in line.split(",") if p.strip()]
        if not parts:
            continue

        kode_roll = parts[0]
        sloc_asal = parts[1] if len(parts) > 1 else "GFGD"
        sloc_tujuan = parts[2] if len(parts) > 2 else "GFGL"
        bin_tujuan = parts[3] if len(parts) > 3 else ""

        payload = {
            "batch": kode_roll,
            "slocs": sloc_asal,
            "slocr": sloc_tujuan,
            "datscan": today,
            "bin": bin_tujuan,
            "note": ""
        }

        try:
            session.get(URL_SESSION_INIT, timeout=8)
            session.post(URL_SAVE_SCAN, data=payload, timeout=8)
            res = session.post(URL_SAVE_POST, data=payload, timeout=8)

            if res.status_code == 200:
                log_results.append(f"✅ [{idx}/{len(lines)}] {kode_roll}: Sukses")
            else:
                log_results.append(f"⚠️ [{idx}/{len(lines)}] {kode_roll}: Gagal HTTP {res.status_code}")
        except Exception as e:
            log_results.append(f"💥 [{idx}/{len(lines)}] {kode_roll}: Error ({str(e)})")

    final_report = "🎉 **Proses Pemindahan Selesai!**\n\n" + "\n".join(log_results)
    await status_msg.edit_text(final_report, parse_mode="Markdown")

if __name__ == "__main__":
    # Jalankan server dummy di latar belakang untuk Render Free Tier
    threading.Thread(target=run_health_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_data))
    app.add_handler(MessageHandler(filters.Document.ALL, process_file_data))
    app.run_polling()
