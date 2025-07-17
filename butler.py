#!/usr/bin/env python3.13

from database import init_database
from dotenv import load_dotenv
import json
import os
from bot import CriticsGuildButler

debug = True

load_dotenv("test.env")
db = init_database()

server_ids = list(json.loads(os.getenv("SERVER_IDS")))
bot_id = int(os.getenv("BOT_ID"))
log_channel_id = int(os.getenv("LOG_CHANNEL_ID"))

bot = CriticsGuildButler(db=db, server_ids=server_ids,bot_id=bot_id,log_channel_id=log_channel_id,print_log=True)

token = os.getenv("DISCORD_TOKEN")
bot.run(token)

if debug:
    input()