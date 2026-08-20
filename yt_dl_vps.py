#!/usr/bin/env python3
import os
import re
import time
import json
import tempfile
import sqlite3
from datetime import datetime
from pathlib import Path
import yt_dlp
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# === CONFIGURATION ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = 1266573274  
LOG_CHANNEL = '@channel username'  
SUPPORT_CHANNEL = '@internet_366'  
SUPPORT_USERNAME = '@codeofsaladin'  
DOWNLOAD_PATH = Path(__file__).parent / 'downloads'
MAX_FILE_SIZE = 50 * 1024 * 1024  
FFMPEG_PATH = '/home/salahpro/ffmpeg'

# Create directories
DOWNLOAD_PATH.mkdir(exist_ok=True)

# === INITIALIZE BOT (Place this right here around line 28) ===
bot = telebot.TeleBot(BOT_TOKEN)

# === DATABASE SETUP ===
DB_PATH = Path(__file__).parent / 'bot_data.db'
...


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

def membership_required(func):
    """Decorator to check membership before executing command"""
    def wrapper(message):
        user_id = message.from_user.id
        if user_id == ADMIN_ID:
            return func(message)
        
        if not check_membership(user_id):
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{SUPPORT_CHANNEL.replace('@', '')}"))
            keyboard.add(InlineKeyboardButton("✅ Check Again", callback_data="check_membership"))
            
            bot.reply_to(
                message,
                f"🔒 **Please join our channel to use this bot!**\n\n"
                f"Click the button below to join, then click 'Check Again'.",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return
        return func(message)
    return wrapper

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

# === MAIN MENU KEYBOARD ===
def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📥 Download"),
        KeyboardButton("📊 Stats")
    )
    keyboard.add(
        KeyboardButton("📢 Channel"),
        KeyboardButton("🆘 Support")
    )
    if ADMIN_ID:
        keyboard.add(KeyboardButton("⚙️ Admin Panel"))
    return keyboard

# === BOT COMMANDS ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    update_last_active(user.id)
    
    # Notify log channel
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
    
    # Welcome message
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📢 Channel", url=f"https://t.me/{SUPPORT_CHANNEL.replace('@', '')}"),
        InlineKeyboardButton("🆘 Support", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")
    )
    keyboard.add(
        InlineKeyboardButton("📥 Download", callback_data="download_help"),
        InlineKeyboardButton("📊 Stats", callback_data="stats_help")
    )
    
    bot.reply_to(
        message,
        f"🎬 **YouTube Downloader Bot**\n\n"
        f"Welcome {user.first_name}! 👋\n\n"
        f"Send me a YouTube URL and I'll download it for you!\n\n"
        f"**Features:**\n"
        f"✅ Multiple quality options\n"
        f"✅ Audio extraction (MP3)\n"
        f"✅ Progress tracking\n"
        f"✅ Fast downloads\n\n"
        f"**Commands:**\n"
        f"/start - Show this menu\n"
        f"/help - Help information\n"
        f"/admin - Admin panel (Admins only)",
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
        f"**Limitations:**\n"
        f"• Max file size: 50MB\n"
        f"• Some videos may be restricted\n"
        f"• Shorts are supported\n\n"
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
        InlineKeyboardButton("📥 Downloads", callback_data="admin_downloads")
    )
    keyboard.add(
        InlineKeyboardButton("🔄 Export Data", callback_data="admin_export"),
        InlineKeyboardButton("❌ Close", callback_data="admin_close")
    )
    
    bot.send_message(
        chat_id,
        f"⚙️ **Admin Panel**\n\n"
        f"📊 Total Users: {total_users}\n"
        f"📥 Total Downloads: {total_downloads}\n"
        f"📅 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Select an option below:",
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
    
    # Handle menu buttons
    if text == "📥 Download":
        bot.reply_to(message, "📤 Send me a YouTube URL to download.")
        return
    
    if text == "📊 Stats":
        total_users, total_downloads = get_user_stats()
        bot.reply_to(
            message,
            f"📊 **Bot Statistics**\n\n"
            f"👤 Total Users: {total_users}\n"
            f"📥 Total Downloads: {total_downloads}\n"
            f"📅 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode='Markdown'
        )
        return
    
    if text == "📢 Channel":
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{SUPPORT_CHANNEL.replace('@', '')}"))
        bot.reply_to(
            message,
            f"📢 **Join our channel for updates!**\n\n"
            f"Stay updated with the latest features and news.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return
    
    if text == "🆘 Support":
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📩 Contact Support", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}"))
        bot.reply_to(
            message,
            f"🆘 **Need help?**\n\n"
            f"Contact our support team for assistance.\n\n"
            f"Support: {SUPPORT_USERNAME}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return
    
    if text == "⚙️ Admin Panel" and user_id == ADMIN_ID:
        show_admin_panel(chat_id)
        return
    
    # Check membership for download
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
    
    # Check if it's a YouTube URL
    youtube_pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)'
    if re.search(youtube_pattern, text):
        handle_download_request(chat_id, text, message.from_user)
    elif not text.startswith('/'):
        bot.reply_to(message, "❌ Please send a valid YouTube URL or use the menu buttons.")

# === DOWNLOAD HANDLER ===
def handle_download_request(chat_id, url, user):
    processing_msg = bot.send_message(chat_id, "🔍 **Fetching video info...**", parse_mode='Markdown')
    
    try:
        info = get_video_info(url)
        if 'error' in info:
            bot.edit_message_text(
                f"❌ **Error:** {info['error']}",
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                parse_mode='Markdown'
            )
            return
        
        title = info['title']
        duration = info['duration']
        
        sessions[chat_id] = {
            'url': url,
            'title': title,
            'duration': duration
        }
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for quality, label in QUALITIES.items():
            buttons.append(InlineKeyboardButton(label, callback_data=f"quality_{quality}"))
        
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                keyboard.add(buttons[i], buttons[i+1])
            else:
                keyboard.add(buttons[i])
        
        keyboard.add(InlineKeyboardButton("❌ Cancel", callback_data="cancel"))
        
        bot.edit_message_text(
            f"🎬 **Choose Quality**\n\n"
            f"📌 **Title:** `{title[:50]}`\n"
            f"⏱️ **Duration:** {format_duration(duration)}\n\n"
            f"Select your preferred quality:",
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
    except Exception as e:
        bot.edit_message_text(
            f"❌ **Error:** {str(e)}",
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            parse_mode='Markdown'
        )

# === CALLBACK HANDLER ===
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id)
    
    # Check membership
    if data == "check_membership":
        if check_membership(user_id):
            bot.edit_message_text(
                "✅ **Membership verified!**\n\nYou can now use the bot.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
        else:
            bot.answer_callback_query(call.id, "❌ Please join the channel first!")
        return
    
    # Download help
    if data == "download_help":
        bot.edit_message_text(
            "📥 **How to download:**\n\n"
            "1️⃣ Send a YouTube URL\n"
            "2️⃣ Choose quality\n"
            "3️⃣ Wait for download\n"
            "4️⃣ Get your file!",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        return
    
    # Stats help
    if data == "stats_help":
        total_users, total_downloads = get_user_stats()
        bot.edit_message_text(
            f"📊 **Bot Statistics**\n\n"
            f"👤 Total Users: {total_users}\n"
            f"📥 Total Downloads: {total_downloads}",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        return
    
    # Admin panel callbacks
    if data == "admin_stats":
        total_users, total_downloads = get_user_stats()
        bot.edit_message_text(
            f"📊 **Bot Statistics**\n\n"
            f"👤 Total Users: {total_users}\n"
            f"📥 Total Downloads: {total_downloads}",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        return
    
    if data == "admin_broadcast":
        bot.edit_message_text(
            "📢 **Send broadcast message**\n\n"
            "Reply to this message with the text you want to broadcast to all users.\n\n"
            "To cancel, send /cancel.",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(call.message, broadcast_message)
        return
    
    if data == "admin_users":
        users = get_all_users()
        if not users:
            bot.edit_message_text(
                "👤 **No users found.**",
                chat_id=chat_id,
                message_id=message_id
            )
            return
        
        user_list = "👤 **User List**\n\n"
        for i, user in enumerate(users[:20], 1):
            user_list += f"{i}. {user[2]} (@{user[1] if user[1] else 'N/A'})\n"
        
        if len(users) > 20:
            user_list += f"\n... and {len(users) - 20} more users."
        
        bot.edit_message_text(
            user_list,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        return
    
    if data == "admin_downloads":
        bot.edit_message_text(
            "📥 **Recent Downloads**\n\n"
            "Check the log channel for detailed download history.",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        return
    
    if data == "admin_export":
        # Export user data
        users = get_all_users()
        export_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        for user in users:
            export_file.write(f"{user[0]} | {user[1]} | {user[2]}\n")
        export_file.close()
        
        with open(export_file.name, 'rb') as f:
            bot.send_document(chat_id, f, caption="📊 Exported user data")
        os.unlink(export_file.name)
        
        bot.edit_message_text(
            "✅ Data exported successfully!",
            chat_id=chat_id,
            message_id=message_id
        )
        return
    
    if data == "admin_close":
        bot.delete_message(chat_id, message_id)
        return
    
    # Cancel download
    if data == 'cancel':
        if chat_id in sessions:
            del sessions[chat_id]
        bot.edit_message_text("❌ Download cancelled.", chat_id=chat_id, message_id=message_id)
        return
    
    # Quality selection
    if data.startswith('quality_'):
        quality = data.replace('quality_', '')
        
        if chat_id not in sessions:
            bot.edit_message_text("⚠️ Session expired. Please send the URL again.", 
                                chat_id=chat_id, message_id=message_id)
            return
        
        session = sessions[chat_id]
        url = session['url']
        title = session['title']
        
        bot.edit_message_text(
            f"⏳ **Downloading...**\n\n"
            f"📌 `{title[:50]}`\n"
            f"🎯 Quality: {QUALITIES.get(quality, quality)}\n\n"
            f"Please wait...",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown'
        )
        
        try:
            download_file(chat_id, url, quality, message_id, title, session)
        except Exception as e:
            bot.edit_message_text(
                f"❌ **Download failed:** {str(e)}",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
        
        if chat_id in sessions:
            del sessions[chat_id]

# === DOWNLOAD FUNCTION ===
def download_file(chat_id, url, quality, message_id, title, session):
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            def progress_hook(d):
                if d['status'] == 'downloading':
                    if 'total_bytes' in d:
                        downloaded = d.get('downloaded_bytes', 0)
                        total = d.get('total_bytes', 1)
                        percent = (downloaded / total) * 100
                        if int(percent) % 10 == 0:
                            try:
                                bot.edit_message_text(
                                    f"⏳ **Downloading...**\n\n"
                                    f"📌 `{title[:40]}`\n"
                                    f"📊 Progress: {int(percent)}%\n"
                                    f"📦 {format_size(downloaded)} / {format_size(total)}",
                                    chat_id=chat_id,
                                    message_id=message_id,
                                    parse_mode='Markdown'
                                )
                            except:
                                pass
                elif d['status'] == 'finished':
                    try:
                        bot.edit_message_text(
                            f"📤 **Processing file...**\n\n"
                            f"Please wait...",
                            chat_id=chat_id,
                            message_id=message_id,
                            parse_mode='Markdown'
                        )
                    except:
                        pass
            
            ydl_opts = get_ydl_opts(quality, temp_path, progress_hook)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            files = list(temp_path.glob('*'))
            if not files:
                raise Exception("No file downloaded")
            
            file_path = max(files, key=lambda f: f.stat().st_size)
            file_size = file_path.stat().st_size
            
            if file_size > MAX_FILE_SIZE:
                bot.edit_message_text(
                    f"❌ **File too large!**\n\n"
                    f"Size: {format_size(file_size)}\n"
                    f"Max allowed: {format_size(MAX_FILE_SIZE)}",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='Markdown'
                )
                log_download(chat_id, url, quality, file_size, "Failed - Too Large")
                return
            
            bot.edit_message_text(
                f"📤 **Uploading...**\n\n"
                f"📌 `{title[:50]}`\n"
                f"📦 {format_size(file_size)}",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
            
            file_extension = file_path.suffix.lower()
            
            with open(file_path, 'rb') as f:
                if quality == 'audio' or file_extension == '.mp3':
                    bot.send_audio(
                        chat_id,
                        f,
                        title=title[:100],
                        performer="@YoutubeDL_R_Bot",
                        caption=f"🎵 **Audio Extracted!**\n\n📌 `{title[:50]}`",
                        parse_mode='Markdown'
                    )
                else:
                    bot.send_video(
                        chat_id,
                        f,
                        caption=f"✅ **Download Complete!**\n\n"
                                f"📌 `{title[:50]}`\n"
                                f"🎯 Quality: {QUALITIES.get(quality, quality)}",
                        parse_mode='Markdown',
                        supports_streaming=True
                    )
            
            # Log download
            log_download(chat_id, url, quality, file_size, "Success")
            
            # Send to log channel
            try:
                bot.send_message(
                    LOG_CHANNEL,
                    f"📥 **New Download**\n\n"
                    f"👤 **User:** {session.get('user_name', 'Unknown')}\n"
                    f"🆔 **ID:** `{chat_id}`\n"
                    f"🎬 **Title:** `{title[:50]}`\n"
                    f"🎯 **Quality:** {QUALITIES.get(quality, quality)}\n"
                    f"📦 **Size:** {format_size(file_size)}\n"
                    f"📅 **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    parse_mode='Markdown'
                )
            except:
                pass
            
            try:
                bot.delete_message(chat_id, message_id)
            except:
                pass
            
    except Exception as e:
        log_download(chat_id, url, quality, 0, f"Failed - {str(e)[:50]}")
        raise Exception(f"Download error: {str(e)}")

# === BROADCAST FUNCTION ===
def broadcast_message(message):
    chat_id = message.chat.id
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Broadcast cancelled.")
        return
    
    if message.from_user.id != ADMIN_ID:
        return
    
    users = get_all_users()
    sent = 0
    failed = 0
    
    progress_msg = bot.reply_to(message, f"📢 Broadcasting to {len(users)} users...")
    
    for user_id, username, first_name in users:
        try:
            bot.send_message(
                user_id,
                f"📢 **Announcement**\n\n{message.text}",
                parse_mode='Markdown'
            )
            sent += 1
        except:
            failed += 1
        
        # Rate limiting
        time.sleep(0.1)
    
    bot.edit_message_text(
        f"📢 **Broadcast Complete**\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}\n"
        f"📊 Total: {len(users)}",
        chat_id=chat_id,
        message_id=progress_msg.message_id,
        parse_mode='Markdown'
    )

# === START BOT ===
if __name__ == '__main__':
    ffmpeg = check_ffmpeg()
    if ffmpeg:
        print(f"✅ FFmpeg found at: {ffmpeg}")
    else:
        print("⚠️ FFmpeg not found! Audio extraction may not work.")
    
    print(f"🤖 Bot is starting...")
    print(f"📁 Download path: {DOWNLOAD_PATH}")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print(f"📢 Log Channel: {LOG_CHANNEL}")
    print(f"📢 Support Channel: {SUPPORT_CHANNEL}")
    print(f"✅ Bot is running! Press Ctrl+C to stop.")
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
