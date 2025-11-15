# Tera

Terabox video downloader Telegram bot with MongoDB user tracking, professional UI, premium tier system, and auto-upload feature.

## ✨ Features

✅ **Professional User Interface** - Interactive inline keyboard menus  
✅ **Download Terabox Videos** - Download videos directly from Terabox links  
✅ **User Statistics** - `/stats` command shows download history and premium status  
✅ **Premium Tier System** - 30-day free trial with premium features  
✅ **Auto-Upload Feature** - Premium users auto-upload downloads to their channel  
✅ **MongoDB Integration** - Track users, downloads, and premium data  
✅ **Store Channel** - Archive all downloads in a store channel  
✅ **Media Caption Support** - Extract links from photo/document/video captions  
✅ **Download Tracking** - Keep statistics on user downloads and activity  

## 🎨 Professional UI

The bot now features:
- **Main Menu** - Interactive buttons: 📊 Stats, ❓ Help, ⭐ Premium
- **Premium Menu** - Activate trial, setup auto-upload
- **Stats Display** - View downloads, join date, membership duration
- **Back Buttons** - Easy navigation throughout menus
- **Dynamic Display** - Premium users see extra options

## Premium Features

- 🔄 **Auto-Upload** - Automatically forward downloads to your Telegram channel
- ⭐ **Premium Status** - 30-day free trial included
- 📊 **Priority Support** - Get help faster
- ⚡ **Enhanced Experience** - All download features available  

## Prerequisites

- Python 3.8+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- MongoDB instance (local or MongoDB Atlas cloud)
- FFmpeg (for M3U8 HLS stream downloads)
- pip (Python package manager)

## Local Setup

### 1. Clone Repository
```bash
git clone https://github.com/strange12345678/Tera.git
cd Tera
```

### 2. Install Dependencies

**Install system dependencies (FFmpeg):**
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install ffmpeg

# macOS (with Homebrew)
brew install ffmpeg

# Windows (with Chocolatey)
choco install ffmpeg
```

**Install Python dependencies:**
```bash
pip install -r requirements.txt
```

### 3. Setup Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` and add your credentials:
```env
# Required
BOT_TOKEN=your_telegram_bot_token_here
MONGODB_URL=mongodb+srv://username:password@cluster.mongodb.net/

# Optional but recommended
ADMIN_ID=your_telegram_user_id
MONGODB_DB_NAME=terabox_bot
DOWNLOAD_DIR=./downloads
LOG_LEVEL=INFO
```

### 4. Get Your Telegram User ID
- Send `/start` to [@userinfobot](https://t.me/userinfobot) on Telegram
- Copy your user ID and paste in `.env` as `ADMIN_ID`

### 5. Setup MongoDB

**Option A: MongoDB Atlas (Cloud - Recommended)**
1. Go to [mongodb.com/cloud/atlas](https://mongodb.com/cloud/atlas)
2. Create a free account and cluster
3. Get your connection string: `mongodb+srv://username:password@cluster.mongodb.net/`
4. Paste in `.env` as `MONGODB_URL`

**Option B: Local MongoDB**
```bash
# Install MongoDB (Ubuntu/Debian)
sudo apt-get install mongodb

# Start MongoDB
sudo systemctl start mongodb

# Connection string in .env
MONGODB_URL=mongodb://localhost:27017
```

### 6. Run the Bot
```bash
python main.py
```

The bot should output:
```
==================================================
Terabox Video Downloader Bot
==================================================
Initializing Terabox Downloader Bot...
Download directory: ./downloads
MongoDB connected successfully
Bot instance created
Starting bot...
Bot is running!
```

## Deploy to Render

### 1. Connect Your Repository
1. Push your code to GitHub
2. Go to [render.com](https://render.com)
3. Create new "Background Worker" service
4. Connect your GitHub repository

### 2. Set Environment Variables
In Render dashboard, set **Environment**:
- `BOT_TOKEN` - Your Telegram bot token
- `MONGODB_URL` - Your MongoDB connection string
- `ADMIN_ID` - Your Telegram user ID
- `MONGODB_DB_NAME` - terabox_bot (or your preferred name)

### 3. Deploy
- Render automatically detects `render.yaml`
- Click "Deploy" and wait for build completion
- Check logs to ensure bot started successfully

**Cost:** Free tier includes 1 free background worker

## Project Structure

```
Tera/
├── main.py                 # Bot entry point
├── config.py              # Configuration & env vars
├── requirements.txt       # Python dependencies
├── .env.example           # Example environment file
├── Procfile               # Deployment config for Render
├── render.yaml            # Render service config
├── README.md              # This file
└── src/
    ├── __init__.py
    ├── database.py        # MongoDB user management
    └── handlers/
        ├── __init__.py
        ├── bot.py         # Main bot handler
        └── download.py    # Terabox download logic
```

## Commands

- `/start` - Start bot and show main menu
- `/help` - Show help menu with back button
- `/stats` - Show your download statistics and premium status
- `/cancel` - Cancel current download operation

## Inline Buttons

**Main Menu:**
- 📊 Stats - View download statistics
- ❓ Help - Show help information
- ⭐ Premium - Access premium features

**Premium Menu:**
- ✅ Activate Premium - Get 30-day free trial
- 🔄 Auto-Upload Setup - Configure channel
- ⬅️ Back - Return to main menu

## How It Works

1. User sends `/start` → Main menu displayed with interactive buttons
2. User clicks buttons → Navigate menus smoothly
3. User sends Terabox link → Bot downloads and sends video
4. For premium users → Auto-uploads to configured channel
5. Stats tracked in MongoDB for later review

## Premium Setup

### For Users
1. Open bot and click `/start`
2. Click ⭐ **Premium** button
3. Click ✅ **Activate Premium** for 30-day trial
4. Click 🔄 **Auto-Upload Setup**
5. Send your channel ID
6. Done! Videos now auto-upload

### Channel ID Format
- Find your channel in Telegram
- Get the ID (usually starts with -100)
- Paste to bot when asked

## Database Schema

User document includes:
```javascript
{
  user_id: 12345,
  first_name: "John",
  downloads_count: 42,
  join_date: "2025-01-15",
  
  // Premium Fields
  is_premium: true,
  premium_until: "2025-02-24",
  auto_upload_channel: "-100123456",
  auto_upload_enabled: true
}
```

## Documentation

- **UI_FEATURES.md** - Technical feature breakdown
- **PROFESSIONAL_UI_GUIDE.md** - User-friendly guide
- **IMPLEMENTATION_SUMMARY.md** - Code statistics
- **QUICK_REFERENCE.md** - Visual flowcharts
- **IMPLEMENTATION_STATUS.md** - Project status

## Troubleshooting

**Bot not responding:**
- Check `BOT_TOKEN` is correct in `.env`
- Verify internet connection
- Check logs: `cat bot.log`

**MongoDB connection failed:**
- Verify `MONGODB_URL` is correct
- Check IP whitelist on MongoDB Atlas (allow 0.0.0.0/0 for testing)
- Ensure MongoDB service is running (if local)

**Download fails:**
- Check if Terabox link is valid
- Verify file size is under 2GB
- Check internet speed for large files

## API Integration

This bot uses:
- **Telegram Bot API** via `python-telegram-bot` library
- **iTeraPlay API** for Terabox video streaming
- **MongoDB** for user data persistence

## License

MIT License

## Support

For issues or questions:
- Check existing issues on GitHub
- Review logs in `bot.log`
- Test with `/help` command in Telegram
