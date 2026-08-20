#!/usr/bin/env python3
import os
import re
import time
import json
import tempfile
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
import yt_dlp
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# === CONFIGURATION ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = 6189362753  
LOG_CHANNEL = '@channel username'  
SUPPORT_CHANNEL = '@ayu_xu'  
SUPPORT_USERNAME = '@ayanafekadu'  
DOWNLOAD_PATH = Path(__file__).parent / 'downloads'
MAX_FILE_SIZE = 50 * 1024 * 1024  
FFMPEG_PATH = '/home/salahpro/ffmpeg'

# Create directories
DOWNLOAD_PATH.mkdir(exist_ok=True)

# === INITIALIZE BOT ===
bot = telebot.TeleBot(BOT_TOKEN)

# === COOKIES CONFIGURATION ===
# Checks Render's Secret Files path first, then falls back to local directory
COOKIE_FILE_PATH = None
possible_cookie_paths = [
    Path('/etc/secrets/cookies.txt'),  # Render Secret Files mount path
    Path(__file__).parent / 'cookies.txt'  # Local project directory
]

for path in possible_cookie_paths:
    if path.exists():
        COOKIE_FILE_PATH = str(path)
        break

# === DATABASE SETUP ===
DB_PATH = Path(__file__).parent / 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        join_date TEXT,
        last_active TEXT,
        is_admin INTEGER DEFAULT 0
    )''')
    
    # Downloads table
    c.execute('''CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        url TEXT,
        quality TEXT,
        file_size INTEGER,
        download_time TEXT,
        status TEXT
    )''')
    
    # Settings table
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    conn.commit()
    conn.close()

init_db()

# === DATABASE FUNCTIONS ===
def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''INSERT OR REPLACE INTO users 
        (user_id, username, first_name, last_name, join_date, last_active, is_admin)
        VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (user_id, username, first_name, last_name, 
         datetime.now().isoformat(), datetime.now().isoformat(), 
         1 if user_id == ADMIN_ID else 0))
    
    conn.commit()
    conn.close()

def update_last_active(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET last_active = ? WHERE user_id = ?', 
              (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def log_download(user_id, url, quality, file_size, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO downloads 
        (user_id, url, quality, file_size, download_time, status)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, url, quality, file_size, datetime.now().isoformat(), status))
    conn.commit()
    conn.close()

def get_user_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total_users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    total_downloads = c.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
    conn.close()
    return total_users, total_downloads

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    users = c.execute('SELECT user_id, username, first_name FROM users').fetchall()
    conn.close()
    return users

# === CHECK MEMBERSHIP ===
def check_membership(user_id):
    """Check if user is a member of the required channel"""
    if not SUPPORT_CHANNEL:
        return True
    
    try:
        member = bot.get_chat_member(SUPPORT_CHANNEL, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# === HELPER FUNCTIONS ===
def format_size(bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} TB"

def format_duration(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def check_ffmpeg():
    ffmpeg_bin = Path(FFMPEG_PATH) / 'ffmpeg'
    if ffmpeg_bin.exists():
        return str(ffmpeg_bin)
    try:
        result = subprocess.run(['which', 'ffmpeg'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return None

def get_video_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'ignoreerrors': True,
    }
    
    if COOKIE_FILE_PATH:
        ydl_opts['cookiefile'] = COOKIE_FILE_PATH

    ffmpeg_path = check_ffmpeg()
    if ffmpeg_path:
        ydl_opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return {'error': 'Could not fetch video info'}
            return {
                'title': info.get('title', 'Unknown Video'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Unknown'),
            }
    except Exception as e:
        return {'error': str(e)}

def get_ydl_opts(quality, output_path, progress_hook=None):
    opts = {
        'outtmpl': str(output_path / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'noplaylist': True,
    }
    
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH

    ffmpeg_path = check_ffmpeg()
    if ffmpeg_path:
        opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path)
    
    if progress_hook:
        opts['progress_hooks'] = [progress_hook]
    
    if quality == 'audio':
        opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    elif quality == 'best':
        opts.update({
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
        })
    else:
        height = quality.replace('p', '')
        opts.update({
            'format': f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]/best',
            'merge_output_format': 'mp4',
        })
    return opts

# === QUALITY OPTIONS ===
QUALITIES = {
    'best': '🎬 Best Quality',
    '1080p': '🎬 1080p (Full HD)',
    '720p': '🎬 720p (HD)',
    '480p': '🎬 480p (SD)',
    'audio': '🎵 Audio Only (MP3)'
}

# === SESSIONS ===
sessions = {}

# === BOT COMMANDS ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    update_last_active(user.id)
    
    try:
        bot.send_message(
            LOG_CHANNEL,
            f"🆕 **New User Started Bot!**\n\n"
            f"👤 **User:** {user.first_name}\n"
            f"🆔 **ID:** `{user.id}`\n"
            f"📛 **Username:** @{user.username if user.username else 'N/A'}\n"
            f"📅 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode='Markdown'
        )
    except:
        pass
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📢 Channel", url=f"https://t.me/{SUPPORT_CHANNEL.replace('@', '')}"),
        InlineKeyboardButton("🆘 Support", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")
    )
    
    bot.reply_to(
        message,
        f"🎬 **YouTube Downloader Bot**\n\n"
        f"Welcome {user.first_name}! 👋\n\n"
        f"Send me a YouTube URL and I'll download it for you!",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['help'])
def send_help(message):
    update_last_active(message.from_user.id)
    bot.reply_to(
        message,
        f"📖 **How to use:**\n\n"
        f"1️⃣ Send a YouTube URL\n"
        f"2️⃣ Choose your preferred quality\n"
        f"3️⃣ Wait for the download\n"
        f"4️⃣ Receive your file!\n\n"
        f"**Support:** {SUPPORT_USERNAME}\n"
        f"**Channel:** {SUPPORT_CHANNEL}",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ You don't have permission to use this command.")
        return
    
    update_last_active(message.from_user.id)
    show_admin_panel(message.chat.id)

def show_admin_panel(chat_id):
    total_users, total_downloads = get_user_stats()
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
    )
    keyboard.add(
        InlineKeyboardButton("👤 Users", callback_data="admin_users"),
        InlineKeyboardButton("❌ Close", callback_data="admin_close")
    )
    
    bot.send_message(
        chat_id,
        f"⚙️ **Admin Panel**\n\n"
        f"📊 Total Users: {total_users}\n"
        f"📥 Total Downloads: {total_downloads}\n"
        f"📅 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# === HANDLE MESSAGES ===
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    text = message.text.strip()
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    update_last_active(user_id)
    
    if user_id != ADMIN_ID and not check_membership(user_id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{SUPPORT_CHANNEL.replace('@', '')}"))
        keyboard.add(InlineKeyboardButton("✅ Check Again", callback_data="check_membership"))
        bot.reply_to(
            message,
            f"🔒 **Please join our channel to download!**\n\n"
            f"Click the button below to join, then click 'Check Again'.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return
    
    youtube_pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)'
    if re.search(youtube_pattern, text):
        handle_download_request(chat_id, text, message.from_user)
    elif not text.startswith('/'):
        bot.reply_to(message, "❌ Please send a valid YouTube URL.")

def handle_download_request(chat_id, url, user):
    processing_msg = bot.send_message(chat_id, "🔍 **Fetching video info...**", parse_mode='Markdown')
    
    try:
        info = get_video_info(url)
        if 'error' in info:
            bot.edit_message_text(f"❌ **Error:** {info['error']}", chat_id=chat_id, message_id=processing_msg.message_id, parse_mode='Markdown')
            return
        
        title = info['title']
        duration = info['duration']
        
        sessions[chat_id] = {'url': url, 'title': title, 'duration': duration, 'user_name': user.first_name}
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        for quality, label in QUALITIES.items():
            keyboard.add(InlineKeyboardButton(label, callback_data=f"quality_{quality}"))
        keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel"))
        
        bot.edit_message_text(
            f"🎬 **Choose Quality**\n\n📌 **Title:** `{title[:50]}`\n⏱️ **Duration:** {format_duration(duration)}",
            chat_id=chat_id, message_id=processing_msg.message_id, parse_mode='Markdown', reply_markup=keyboard
        )
    except Exception as e:
        bot.edit_message_text(f"❌ **Error:** {str(e)}", chat_id=chat_id, message_id=processing_msg.message_id, parse_mode='Markdown')

# === CALLBACK HANDLER ===
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id)
    
    if data == "check_membership":
        if check_membership(user_id):
            bot.edit_message_text("✅ **Membership verified!** You can now send your URL.", chat_id=chat_id, message_id=message_id, parse_mode='Markdown')
        else:
            bot.answer_callback_query(call.id, "❌ Please join the channel first!", show_alert=True)
        return
    
    if data == "admin_stats":
        total_users, total_downloads = get_user_stats()
        bot.edit_message_text(f"📊 **Bot Statistics**\n\n👤 Total Users: {total_users}\n📥 Total Downloads: {total_downloads}", chat_id=chat_id, message_id=message_id, parse_mode='Markdown')
        return
    
    if data == "admin_close":
        bot.delete_message(chat_id, message_id)
        return
    
    if data == 'cancel':
        sessions.pop(chat_id, None)
        bot.edit_message_text("❌ Download cancelled.", chat_id=chat_id, message_id=message_id)
        return
    
    if data.startswith('quality_'):
        quality = data.replace('quality_', '')
        session = sessions.get(chat_id)
        if not session:
            bot.edit_message_text("⚠️ Session expired. Send URL again.", chat_id=chat_id, message_id=message_id)
            return
        
        bot.edit_message_text("⏳ **Downloading...** Please wait.", chat_id=chat_id, message_id=message_id, parse_mode='Markdown')
        try:
            download_file(chat_id, session['url'], quality, message_id, session['title'], session)
        except Exception as e:
            bot.edit_message_text(f"❌ **Download failed:** {str(e)}", chat_id=chat_id, message_id=message_id, parse_mode='Markdown')
        sessions.pop(chat_id, None)

def download_file(chat_id, url, quality, message_id, title, session):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        ydl_opts = get_ydl_opts(quality, temp_path)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        files = list(temp_path.glob('*'))
        if not files:
            raise Exception("No file downloaded")
        
        file_path = max(files, key=lambda f: f.stat().st_size)
        file_size = file_path.stat().st_size
        
        if file_size > MAX_FILE_SIZE:
            bot.edit_message_text(f"❌ File too large ({format_size(file_size)}). Max is 50MB.", chat_id=chat_id, message_id=message_id)
            log_download(chat_id, url, quality, file_size, "Failed - Too Large")
            return
        
        bot.edit_message_text("📤 **Uploading file...**", chat_id=chat_id, message_id=message_id, parse_mode='Markdown')
        with open(file_path, 'rb') as f:
            if quality == 'audio':
                bot.send_audio(chat_id, f, title=title[:100], performer="@Bot", caption=f"🎵 `{title[:50]}`", parse_mode='Markdown')
            else:
                bot.send_video(chat_id, f, caption=f"✅ `{title[:50]}`", parse_mode='Markdown', supports_streaming=True)
        
        log_download(chat_id, url, quality, file_size, "Success")
        bot.delete_message(chat_id, message_id)

if __name__ == '__main__':
    print(f"🤖 Bot is starting with cookies path: {COOKIE_FILE_PATH}")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
