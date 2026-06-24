import discord
from discord.ext import commands, tasks
import json
import os
import io
import logging
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import aiohttp

# --- 設定関連 ---
logging.basicConfig(level=logging.INFO)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
raw_REGIONCODES = os.getenv("REGION_CODES")
if raw_REGIONCODES:
    REGION_CODES = json.loads(raw_REGIONCODES)
else:
    REGION_CODES = {"東京都": "130000"}

CONFIG_FILE = "config.json"
alert_sent = False
last_alert_check = datetime.min

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"city": "Tokyo", "mode": "detail", "time": "07:00", "channel_id": None, "alert_threshold": 50, "alert_interval": 60}
    with open(CONFIG_FILE, "r") as f: return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f: json.dump(config, f)

async def fetch_json(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as res:
            if res.status != 200:
                raise Exception(f"HTTP Error:{res.status}")
            return await res.json()

# --- Botの初期化 ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

# --- 各種関数 ---
async def get_weather_data(city):
    geo_url = f"https://nominatim.openstreetmap.org/search?q={city}&format=json&limit=1"
    res = await fetch_json(geo_url)
    if not res: raise Exception("その場所のデータは見つからなかったよ")
    lat, lon = res[0]['lat'], res[0]['lon']
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation_probability"
    return await fetch_json(url)

def create_graph(data):
    times = [t[11:16] for t in data['hourly']['time'][:24]]
    temps = data['hourly']['temperature_2m'][:24]
    precip = data['hourly']['precipitation_probability'][:24]
    
    fig, ax1 = plt.subplots(figsize=(10, 5))
    
    line1 = ax1.plot(times, temps, color='red', marker='o', markersize=4, label='Temperature (°C)', linewidth=2)

    ax1.set_xlabel('Time')
    ax1.set_ylabel('Temperature (°C)', color='black')
    ax1.tick_params(axis='y', labelcolor='black')
    ax1.axhline(0, color='gray', linestyle='--', linewidth=0.8)
    ax1.set_xticks(range(0, 24, 3))
    ax2 = ax1.twinx()
    bar1 = ax2.bar(times, precip, color='blue', alpha=0.3, label='Precipitation (%)')
    lines = line1 + [bar1]
    labels = ['Temperature (°C)', 'Precipitation (%)']
    ax1.legend(lines, labels, loc='upper left')
    
    ax2.set_ylabel('Precipitation (%)', color='black')
    ax2.set_ylim(0, 100)
    ax2.tick_params(axis='y', labelcolor='black')

    plt.xticks(rotation=45)
    plt.title('Weather Forecast')
    fig.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

def get_weather_summary(data):
    precip = data['hourly']['precipitation_probability'][:24]
    max_p = max(precip)
    
    if max_p < 20:
        return "晴れやかな一日になりそう。ピクニック日和だね！"
    elif max_p < 50:
        return "曇った日になりそう。所によっては雨が降りそうだから折り畳み傘を持っておこう！"
    else:
        return "雨が降る時間帯がありそうだね。傘を忘れずに！"

def is_configured_channel(ctx):
    config = load_config()
    if config.get("channel_id") is None: return True
    return ctx.channel.id == config["channel_id"]

# --- コマンド ---
@bot.command()
@commands.check(is_configured_channel)
async def setting(ctx, command_type: str, value: str = None):
    config = load_config()
    
    if command_type.lower() == "channel":
        config["channel_id"] = ctx.channel.id
        save_config(config)
        await ctx.send(f"通知先を「{ctx.channel.name}」に設定したよ。")
        return
    
    if value is None:
        await ctx.send(f"エラー: `{command_type}` の後に値を入力してね。(例: `!setting {command_type} [設定値]`)")
        return
    
    if command_type.lower() == "mode" and value.lower() in ["simple", "detail", "sleep"]:
        config["mode"] = value
    elif command_type.lower() == "city":
        config["city"] = value
    elif command_type.lower() == "time":
        config["time"] = value
    elif command_type.lower() == "threshold":
        config["alert_threshold"] = int(value)
    elif command_type.lower() == "interval":
        config["alert_interval"] = int(value)
    else:
        await ctx.send("設定エラー: 指定された項目が見つからないようだね。")
        return
    
    save_config(config)
    await ctx.send(f"{command_type}を「{value}」に変更したよ。")

async def send_weather_forecast(channel):
    config = load_config()
    try:
        data = await get_weather_data(config["city"])
        summary = get_weather_summary(data)
        message = f"【{config['city']}の天気傾向】\n{summary}"

        if config["mode"] == "simple":
            await channel.send(message)
        elif config["mode"] == "detail":
            graph = create_graph(data)
            await channel.send(message, file=discord.File(graph, 'weather.png'))

    except Exception as e:
        logging.error(e)
        await channel.send("APIの調子が悪いみたい。天気は外を見てね^^")

@bot.command()
@commands.check(is_configured_channel)
async def forecast(ctx):
    await send_weather_forecast(ctx)

async def help(ctx):
    help_text = """**天気Bot コマンド一覧**
- `!forecast` : 今すぐ天気予報を確認する
- `!setting mode [simple|detail|sleep]` : 表示モードの変更
- `!setting city [地名]` : 対象地域を変更
- `!setting time [HH:MM]` : 自動通知時刻を変更
- `!setting threshold [数値]` : 雨アラートの降水確率閾値を変更
- `!setting interval [分]` : 雨アラートの監視間隔を変更
- `!setting channel` : このチャンネルを通知先に設定する
- `!help` : このメッセージを表示"""
    await ctx.send(help_text)

# --- 警報用のマッピングと関数 ---
last_alert = None

async def check_disaster_alerts(channel, city):
    global last_alert
    code = REGION_CODES.get(city, "2720300") 
    url = f"https://www.jma.go.jp/bosai/warning/data/warning/{code}.json"

    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            async with session.get(url) as response:

                data = await response.json()
                alert_items = data.get('alert', []) 
                active_warnings = [item['name'] for item in alert_items if item['type'] == "1"]
                
                if active_warnings:
                    alert_msg = f"**【緊急】警報が発令されているよ!**\n対象: {', '.join(active_warnings)}"
                    if last_alert != alert_msg:
                        await channel.send(alert_msg)
                        last_alert = alert_msg
                else:
                    last_alert = None
    except Exception as e:
        logging.error(f"警報チェックエラー: {e}")

# --- タスクと起動 ---
@tasks.loop(minutes=1)
async def main_loop():
    global alert_sent, last_alert_check
    config = load_config()

    if config["mode"] == "sleep" or not config.get("channel_id"): return

    channel = bot.get_channel(config["channel_id"])
    if not channel:return
    target_hour, target_minute = map(int, config["time"].split(":"))
    now = datetime.now()
    target_dt = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    if target_dt <= now < target_dt + timedelta(minutes=1):
        await send_weather_forecast(channel)
            
    if datetime.now() >= last_alert_check + timedelta(minutes=config.get("alert_interval", 60)):
        try:
            data = await get_weather_data(config["city"])
            precip_list = data['hourly']['precipitation_probability'][:3]
            if any(p >= config.get("alert_threshold", 60) for p in precip_list):
                if not alert_sent:
                    await channel.send(f"{config['city']}で近々雨が降りそうだよ！")
                    alert_sent = True
            else:
                alert_sent = False

            last_alert_check = datetime.now()
        except Exception as e:
            logging.error(f"エラー:{e}")
    
    if now.minute % 10 == 0:
        await check_disaster_alerts(channel, config.get("city", "東京都"))

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("-"*30)
    print(f"Bot名: {bot.user.name}")
    print(f"Bot ID: {bot.user.id}")
    print("-"*30)
    print("Botは現在待機中です。Discordでコマンドを入力してください。")
    main_loop.start()

bot.run(TOKEN)