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
open_list_channel_id = int(os.getenv("OPEN_LIST_CHANNEL_ID"))
open_list_tag_ids = list(json.loads(os.getenv("OPEN_LIST_TAG_IDS")))
critic_list_channel_id = int(os.getenv("CRITIC_LIST_CHANNEL_ID"))
critic_list_tag_ids = list(json.loads(os.getenv("CRITIC_LIST_TAG_IDS")))
trusted_critic_list_channel_id = int(os.getenv("TRUSTED_CRITIC_LIST_CHANNEL_ID"))
trusted_critic_list_tag_ids = list(json.loads(os.getenv("TRUSTED_CRITIC_LIST_TAG_IDS")))
monthly_tokens = int(os.getenv("MONTHLY_TOKENS"))
max_requests = int(os.getenv("MAX_REQUESTS"))
max_penalties = int(os.getenv("MAX_PENALTIES"))

bot = CriticsGuildButler(db_connect=connect,
                        server_ids=server_ids,
                        bot_id=bot_id,
                        log_channel_id=log_channel_id,
                        trusted_critic_role_id=trusted_critic_role_id,
                        open_list_channel_id=open_list_channel_id,
                        open_list_tag_ids=open_list_tag_ids,
                        critic_list_channel_id=critic_list_channel_id,
                        critic_list_tag_ids=critic_list_tag_ids,
                        trusted_critic_list_channel_id=trusted_critic_list_channel_id,
                        trusted_critic_list_tag_ids=trusted_critic_list_tag_ids,
                        monthly_tokens=monthly_tokens,
                        max_requests=max_requests,
                        max_penalties=max_penalties,
                        print_log=True)

token = os.getenv("DISCORD_TOKEN")
bot.run(token)

if debug:
    input()