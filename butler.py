#!/usr/bin/env python3.13

from database import connect, init_database
from dotenv import load_dotenv
import json
import os
from bot import CriticsGuildButler

debug = False

load_dotenv("test.env")
init_database()

server_ids = list(json.loads(os.getenv("SERVER_IDS")))
bot_id = int(os.getenv("BOT_ID"))
log_channel_id = int(os.getenv("LOG_CHANNEL_ID"))
trusted_critic_role_id = int(os.getenv("TRUSTED_CRITIC_ROLE_ID"))
monthly_tokens = int(os.getenv("MONTHLY_TOKENS"))

bot = CriticsGuildButler(db_connect=connect,
                        server_ids=server_ids,
                        bot_id=bot_id,
                        log_channel_id=log_channel_id,
                        trusted_critic_role_id=trusted_critic_role_id,
                        monthly_tokens=monthly_tokens,
                        print_log=True)

token = os.getenv("DISCORD_TOKEN")
bot.run(token)

if debug:
    input()