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
critic_role_id = int(os.getenv("CRITIC_ROLE_ID"))
trusted_critic_role_id = int(os.getenv("TRUSTED_CRITIC_ROLE_ID"))
open_list_channel_id = int(os.getenv("OPEN_LIST_CHANNEL_ID"))
open_list_tag_ids = list(json.loads(os.getenv("OPEN_LIST_TAG_IDS")))
critic_list_channel_id = int(os.getenv("CRITIC_LIST_CHANNEL_ID"))
critic_list_tag_ids = list(json.loads(os.getenv("CRITIC_LIST_TAG_IDS")))
critic_list_token_costs = list(json.loads(os.getenv("CRITIC_LIST_TOKEN_COSTS")))
critic_list_token_rewards = list(json.loads(os.getenv("CRITIC_LIST_TOKEN_REWARDS")))
trusted_critic_list_channel_id = int(os.getenv("TRUSTED_CRITIC_LIST_CHANNEL_ID"))
trusted_critic_list_tag_ids = list(json.loads(os.getenv("TRUSTED_CRITIC_LIST_TAG_IDS")))
trusted_critic_list_token_costs = list(json.loads(os.getenv("TRUSTED_CRITIC_LIST_TOKEN_COSTS")))
trusted_critic_list_token_rewards = list(json.loads(os.getenv("TRUSTED_CRITIC_LIST_TOKEN_REWARDS")))
monthly_tokens = int(os.getenv("MONTHLY_TOKENS"))
max_requests = int(os.getenv("MAX_REQUESTS"))
max_penalties = int(os.getenv("MAX_PENALTIES"))
days_double_tokens = int(os.getenv("DAYS_DOUBLE_TOKENS"))
react_sleep = int(os.getenv("REACT_SLEEP"))
publish_channel_id = int(os.getenv("PUBLISH_CHANNEL_ID"))
leaderboard_task_weekday = int(os.getenv("LEADERBOARD_TASK_WEEKDAY"))
leaderboard_task_hour = int(os.getenv("LEADERBOARD_TASK_HOUR"))
token_cycle_task_monthday = int(os.getenv("TOKEN_CYCLE_TASK_MONTHDAY"))
token_cycle_task_hour = int(os.getenv("TOKEN_CYCLE_TASK_HOUR"))
token_decay = float(os.getenv("TOKEN_DECAY"))

bot = CriticsGuildButler(db_connect=connect,
                        server_ids=server_ids,
                        bot_id=bot_id,
                        log_channel_id=log_channel_id,
                        critic_role_id=critic_role_id,
                        trusted_critic_role_id=trusted_critic_role_id,
                        open_list_channel_id=open_list_channel_id,
                        open_list_tag_ids=open_list_tag_ids,
                        critic_list_channel_id=critic_list_channel_id,
                        critic_list_tag_ids=critic_list_tag_ids,
                        critic_list_token_costs=critic_list_token_costs,
                        critic_list_token_rewards=critic_list_token_rewards,                        
                        trusted_critic_list_channel_id=trusted_critic_list_channel_id,
                        trusted_critic_list_tag_ids=trusted_critic_list_tag_ids,
                        trusted_critic_list_token_costs=trusted_critic_list_token_costs,
                        trusted_critic_list_token_rewards=trusted_critic_list_token_rewards,                        
                        monthly_tokens=monthly_tokens,
                        max_requests=max_requests,
                        max_penalties=max_penalties,
                        days_double_tokens=days_double_tokens,
                        react_sleep=react_sleep,
                        publish_channel_id=publish_channel_id,
                        leaderboard_task_weekday=leaderboard_task_weekday,
                        leaderboard_task_hour=leaderboard_task_hour,
                        token_cycle_task_monthday=token_cycle_task_monthday,
                        token_cycle_task_hour=token_cycle_task_hour,
                        token_decay=token_decay,
                        print_log=True)

token = os.getenv("DISCORD_TOKEN")
bot.run(token)

if debug:
    input()