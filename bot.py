import os
import asyncio
import logging
import datetime
import json
import re
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
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

# ====================================================
# 1. STRUKTUR & HELPER LOGIKA UTAMA SCRIPT V12.0.6
# ====================================================

def normalize_sloc_name(val):
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

def is_tsi_raw_barcode(code):
    if not code:
        return False
    clean = str(code).strip().upper()
    is_format_valid = bool(re.match(r'^[A-Z0-9\-_/ ]{5,30}$', clean))
    has_letters = bool(re.search(r'[A-Z]', clean))
    has_digits = bool(re.search(r'\d', clean))
    is_system_text = 'TEX' in clean or 'REG' in clean or 'NAME' in clean
    is_material_code_pattern = bool(re.search(r'[A-Z]{3,}\d{3,}', clean)) and len(clean) >= 15 and ' ' not in clean

    return is_format_valid and has_letters and has_digits and not is_system_text and not is_material_code_pattern

def extract_bin_code(item):
    if not item or not isinstance(item, dict):
        return '-'
    val = (item.get('CODE_BIN') or item.get('CODEBIN') or item.get('Code Bin') or 
           item.get('code_bin') or item.get('CODE BIN') or item.get('BIN') or 
           item.get('BIN_LOC') or item.get('BINLOC') or item.get('RAK') or 
           item.get('BIN_CODE') or item.get('STORAGE_BIN') or item.get('LOCATION') or '-')
    val = str(val).strip()
    return val if val and val.lower() not in ['nan', 'null', 'undefined'] else '-'

# Memory / Config State Pengguna
USER_CONFIGS = {}

def get_user_cfg(user_id):
    if user_id not in USER_CONFIGS:
        USER_CONFIGS[user_id] = {
            "mode_type": "API_DIRECT",      # API_DIRECT, HIDDEN_NATIVE, UI_INJECT
            "sloc_rule": "AUTO_SWAP",       # AUTO_SWAP, GFGD_TO_GFGL, GFGL_TO_GFGD, MANUAL
            "sloc_sender": "GFGD",          # Kasus Manual
            "sloc_receiver": "GFGL",        # Kasus Manual
            "bin_rule": "INTERIM",          # INTERIM, ORIGINAL, EMPTY, MANUAL
            "custom_bin": "",
            "notepad_text": "",
            "saved_batches": []             # Memori Pindaian
        }
    return USER_CONFIGS[user_id]

# ====================================================
# 2. NAVIGASI TOMBOL (INLINE KEYBOARD)
# ====================================================

def build_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🟢 Smart Queue Auto-Input", callback_data="btn_run_queue"),
            InlineKeyboardButton("⚡ Cek Real-Time", callback_data="btn_check_stock")
        ],
        [
            InlineKeyboardButton("🔄 Aturan Sloc", callback_data="menu_sloc_rules"),
            InlineKeyboardButton("📦 Aturan Bin Fallback", callback_data="menu_bin_rules")
        ],
        [
            InlineKeyboardButton("📊 Export CSV TSIRaw", callback_data="btn_export_csv"),
            InlineKeyboardButton("💾 Memori Pindaian", callback_data="menu_memory")
        ],
        [
            InlineKeyboardButton("🧹 Bersihkan Input Notepad", callback_data="btn_clear_input")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ====================================================
# 3. ENGINE EXECUTION VIA PLAYWRIGHT (NATIVE V12.0.6)
# ====================================================

async def run_v12_engine(user_id, action_type):
    cfg = get_user_cfg(user_id)
    input_text = cfg["notepad_text"] if cfg["notepad_text"].strip() else "\n".join(cfg["saved_batches"])
    lines = [line.strip() for line in input_text.strip().split('\n') if line.strip()]

    if not lines and action_type != "CHECK_STOCK":
        return "⚠️ Tidak ada daftar roll di dalam Notepad atau Memori pindaian!", None

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

        today_str = datetime.date.today().strftime("%Y-%m-%d")

        try:
            # 1. Login Sesi Ke TSI Raw
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            user_input = page.locator("input[name*='user' i], input[name*='email' i], input[id*='user' i]").first
            pass_input = page.locator("input[type='password']").first
            
            if await user_input.count() > 0 and await pass_input.count() > 0:
                await user_input.fill(TSI_USERNAME)
                await pass_input.fill(TSI_PASSWORD)
                btn = page.locator("button[type='submit'], input[type='submit'], .btn-primary").first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_load_state("networkidle")

            await page.goto(f"{BASE_URL}/brctsloc", wait_until="networkidle")

            # 2. Skrip JS Native Fetch v12.0.6 (Dijalankan Langsung Di Browser VPS)
            js_engine = """
            async ([lines, actionType, slocRule, binRule, customBin, senderManual, receiverManual, todayStr]) => {
                const results = [];
                const csvData = [];

                function normalizeSloc(val) {
                    if (!val) return 'GFGD';
                    const clean = val.toString().toUpperCase().trim();
                    if (clean.includes('DALAM') || clean === 'GFGD') return 'GFGD';
                    if (clean.includes('LUAR') || clean === 'GFGL') return 'GFGL';
                    if (clean.includes('PRODUKSI') || clean === 'PROD') return 'PROD';
                    return clean;
                }

                function extractBin(item) {
                    if (!item) return '-';
                    const val = item.CODE_BIN || item.CODEBIN || item['Code Bin'] || item.code_bin || item['CODE BIN'] ||
                              item.BIN || item.BIN_LOC || item.BINLOC || item.RAK || item.BIN_CODE ||
                              item.STORAGE_BIN || item.LOCATION || item.bin || '-';
                    const clean = val.toString().trim();
                    return (clean && clean !== 'nan' && clean !== 'null' && clean !== 'undefined') ? clean : '-';
                }

                for (let line of lines) {
                    if (!line.trim()) continue;
                    const parts = line.split(/[,;\\s]+/).map(p => p.trim()).filter(Boolean);
                    const code = parts[0] ? parts[0].toUpperCase() : '';
                    if (!code) continue;

                    // Fetch Stok Awal
                    let stockItem = null;
                    try {
                        const resStock = await fetch('/rstock/get_stock', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
                            body: new URLSearchParams({ 'mat':'', 'sloc':'', 'batch': code, 'cust':'', 'refr':'', 'shift':'' })
                        });
                        const stockData = await resStock.json();
                        if (Array.isArray(stockData) && stockData.length > 0) {
                            stockItem = stockData[0];
                        }
                    } catch(e) {}

                    // Jika Hanya Cek Stok Real-Time
                    if (actionType === 'CHECK_STOCK') {
                        if (stockItem) {
                            const sloc = stockItem.SLOC || 'N/A';
                            const bin = extractBin(stockItem);
                            const grade = stockItem.GRADE || '-';
                            const meter = stockItem.LENGTH || stockItem.LENGTH_M || '0';
                            const matName = stockItem.NAME || stockItem.MATERIAL || '-';
                            results.push(`• **${code}** | Grd: \`${grade}\` | Sloc: \`${sloc}\` | Bin: \`${bin}\` | Qty: \`${meter}m\`\n📦 \`${matName}\``);
                        } else {
                            results.push(`⚠️ **${code}**: Tidak ditemukan di stok aktif`);
                        }
                        continue;
                    }

                    // Penentuan Logika Sloc & Bin Fallback v12.0.6
                    let currentSloc = stockItem ? (stockItem.SLOC || 'GFGD') : 'GFGD';
                    let originalBin = stockItem ? extractBin(stockItem) : '-';

                    let senderText = normalizeSloc(currentSloc);
                    let receiverText = '';

                    if (parts[1]) {
                        receiverText = normalizeSloc(parts[1]);
                    } else {
                        if (slocRule === 'AUTO_SWAP') {
                            if (currentSloc.includes('DALAM') || currentSloc === 'GFGD') { senderText = 'GFGD'; receiverText = 'GFGL'; }
                            else if (currentSloc.includes('LUAR') || currentSloc === 'GFGL') { senderText = 'GFGL'; receiverText = 'GFGD'; }
                            else if (currentSloc.includes('PRODUKSI') || currentSloc === 'PROD') { senderText = 'PROD'; receiverText = 'GFGD'; }
                            else { receiverText = 'GFGL'; }
                        } else if (slocRule === 'GFGD_TO_GFGL') { senderText = 'GFGD'; receiverText = 'GFGL'; }
                        else if (slocRule === 'GFGL_TO_GFGD') { senderText = 'GFGL'; receiverText = 'GFGD'; }
                        else if (slocRule === 'MANUAL') { senderText = senderManual; receiverText = receiverManual; }
                    }

                    let targetBin = '';
                    if (parts[2]) {
                        targetBin = parts[2].toUpperCase();
                    } else {
                        if (binRule === 'INTERIM') { targetBin = receiverText.includes('GFGD') ? 'A00-00-00' : 'C00-00-00'; }
                        else if (binRule === 'ORIGINAL') { targetBin = (originalBin && originalBin !== '-') ? originalBin : ''; }
                        else if (binRule === 'EMPTY') { targetBin = ''; }
                        else if (binRule === 'MANUAL') { targetBin = customBin.toUpperCase(); }
                    }

                    // Export CSV
                    if (actionType === 'EXPORT_CSV') {
                        if (stockItem) {
                            csvData.push([
                                stockItem.BATCH || code,
                                (stockItem.MATERIAL || stockItem.NAME || '-').replace(/,/g, ' '),
                                (stockItem.SLOC || '-').replace(/,/g, ' '),
                                extractBin(stockItem).replace(/,/g, ' '),
                                stockItem.LENGTH || stockItem.LENGTH_M || '0',
                                stockItem.WEIGHT || stockItem.WEIGHTN || '0',
                                stockItem.GRADE || '-',
                                (stockItem.CUST || stockItem.CUSTOMER || '-').replace(/,/g, ' ')
                            ].join(','));
                        } else {
                            csvData.push([code, 'TIDAK_DITEMUKAN', '-', '-', '0', '0', '-', '-'].join(','));
                        }
                        continue;
                    }

                    // Eksekusi API Direct v12.0.6 (/ttranslist/save_scan & /ttranslist/save_post)
                    const postData = new URLSearchParams({
                        'batch': code,
                        'slocs': senderText,
                        'slocr': receiverText,
                        'datscan': todayStr,
                        'bin': targetBin,
                        'note': ''
                    });

                    try {
                        await fetch('/ttranslist/save_scan', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
                            body: postData
                        });

                        const resPost = await fetch('/ttranslist/save_post', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' },
                            body: postData
                        });

                        const textPost = await resPost.text();
                        let jsonPost = {};
                        try { jsonPost = JSON.parse(textPost); } catch(e) { jsonPost = { message: textPost }; }

                        const binTag = targetBin ? ` (Bin: ${targetBin})` : '';
                        results.push(`✅ \`${code}\`: ${senderText} ➔ ${receiverText}${binTag} [Posted]`);
                    } catch(err) {
                        results.push(`❌ \`${code}\`: Gagal Transfer API`);
                    }
                }

                return { results, csvData };
            }
            """

            exec_out = await page.evaluate(
                js_engine,
                [lines, action_type, cfg["sloc_rule"], cfg["bin_rule"], cfg["custom_bin"], cfg["sloc_sender"], cfg["sloc_receiver"], today_str]
            )

            await browser.close()

            if action_type == "EXPORT_CSV":
                header = ["BATCH,MATERIAL,SLOC,BIN,QTY_METER,WEIGHT_KG,GRADE,CUSTOMER"]
                full_csv = "\n".join(header + exec_out.get("csvData", []))
                return "📊 **Ekspor CSV Berhasil!**", full_csv

            header_title = "⚡ **Hasil Cek Real-Time Stok:**\n\n" if action_type == "CHECK_STOCK" else "🎉 **Hasil Smart Queue v12.0.6:**\n\n"
            return header_title + "\n".join(exec_out.get("results", [])), None

        except Exception as e:
            await browser.close()
            return f"❌ Terjadi kesalahan di VPS: {str(e)}", None

# ====================================================
# 4. BOT EVENT & CALLBACK HANDLER TELEGRAM
# ====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cfg = get_user_cfg(user_id)

    msg_text = (
        "💀 **TSI RAW WORKSTATION BOT (v12.0.6)**\n"
        "━━━━━━━ CONFIG SYSTEM ━━━━━━━\n"
        f"• **Akun TSI**: `{TSI_USERNAME}`\n"
        f"• **Aturan Sloc**: `{cfg['sloc_rule']}`\n"
        f"• **Aturan Bin**: `{cfg['bin_rule']}`\n"
        f"• **Memori Tersimpan**: `{len(cfg['saved_batches'])} Roll`\n\n"
        "Silakan pilih menu di bawah ini atau langsung kirimkan daftar roll ke chat:"
    )

    if update.message:
        await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=build_main_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg_text, parse_mode="Markdown", reply_markup=build_main_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    cfg = get_user_cfg(user_id)

    if query.data == "btn_run_queue":
        await query.edit_message_text("⏳ **Menjalankan Smart Queue Auto-Input v12.0.6...**", parse_mode="Markdown")
        res_text, _ = await run_v12_engine(user_id, "QUEUE_TRANSFER")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")]])
        await context.bot.send_message(chat_id=user_id, text=res_text, parse_mode="Markdown", reply_markup=kb)

    elif query.data == "btn_check_stock":
        await query.edit_message_text("⏳ **Mengecek Real-Time Stok Server TSI...**", parse_mode="Markdown")
        res_text, _ = await run_v12_engine(user_id, "CHECK_STOCK")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Utama", callback_data="main_menu")]])
        await context.bot.send_message(chat_id=user_id, text=res_text, parse_mode="Markdown", reply_markup=kb)

    elif query.data == "btn_export_csv":
        await query.edit_message_text("⏳ **Membuat File CSV TSIRaw Export...**", parse_mode="Markdown")
        res_text, csv_content = await run_v12_engine(user_id, "EXPORT_CSV")
        if csv_content:
            file_bytes = io.BytesIO(csv_content.encode('utf-8'))
            file_bytes.name = f"Rekap_TSIRaw_{datetime.date.today().strftime('%Y%m%d')}.csv"
            await context.bot.send_document(chat_id=user_id, document=InputFile(file_bytes), caption="✔ File Rekap CSV Excel Siap!")
        else:
            await context.bot.send_message(chat_id=user_id, text=res_text, parse_mode="Markdown")

    elif query.data == "menu_sloc_rules":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Auto Swap (Dalam ↔ Luar)", callback_data="set_sloc_AUTO_SWAP")],
            [InlineKeyboardButton("➡️ Selalu Dalam ➔ Luar", callback_data="set_sloc_GFGD_TO_GFGL")],
            [InlineKeyboardButton("⬅️ Selalu Luar ➔ Dalam", callback_data="set_sloc_GFGL_TO_GFGD")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
        ])
        await query.edit_message_text("🔄 **PILIH ATURAN SLOC (FALLBACK):**", parse_mode="Markdown", reply_markup=kb)

    elif query.data.startswith("set_sloc_"):
        cfg["sloc_rule"] = query.data.replace("set_sloc_", "")
        await start(update, context)

    elif query.data == "menu_bin_rules":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Auto Area Interim (A00/C00)", callback_data="set_bin_INTERIM")],
            [InlineKeyboardButton("📌 Bin Asal Stok (Fallback)", callback_data="set_bin_ORIGINAL")],
            [InlineKeyboardButton("🚫 Tanpa Bin (Kosongkan)", callback_data="set_bin_EMPTY")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
        ])
        await query.edit_message_text("📦 **PILIH ATURAN KODE BIN:**", parse_mode="Markdown", reply_markup=kb)

    elif query.data.startswith("set_bin_"):
        cfg["bin_rule"] = query.data.replace("set_bin_", "")
        await start(update, context)

    elif query.data == "menu_memory":
        count = len(cfg["saved_batches"])
        text = (
            f"💾 **MANAJEMEN MEMORI PINDAIAN**\n\n"
            f"Jumlah roll tersimpan: `{count} Roll`\n"
            f"Daftar: `{', '.join(cfg['saved_batches'][:10])}`" + ("..." if count > 10 else "")
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Hapus Memori", callback_data="clear_memory")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]
        ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

    elif query.data == "clear_memory":
        cfg["saved_batches"] = []
        await start(update, context)

    elif query.data == "btn_clear_input":
        cfg["notepad_text"] = ""
        await query.edit_message_text("🧹 **Notepad Berhasil Dibersihkan!**", parse_mode="Markdown")
        await asyncio.sleep(1)
        await start(update, context)

    elif query.data == "main_menu":
        await start(update, context)

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return
    
    user_id = update.effective_user.id
    cfg = get_user_cfg(user_id)
    cfg["notepad_text"] = text

    lines = text.strip().split('\n')
    for line in lines:
        code = line.split(',')[0].strip().upper()
        if is_tsi_raw_barcode(code) and code not in cfg["saved_batches"]:
            cfg["saved_batches"].append(code)

    await update.message.reply_text(
        f"📝 **{len(lines)} Baris Diterima ke Notepad!**\nPilih tindakan melalui menu tombol di bawah:",
        parse_mode="Markdown",
        reply_markup=build_main_keyboard()
    )

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    print("Bot TSI Raw Workstation v12.0.6 Berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
