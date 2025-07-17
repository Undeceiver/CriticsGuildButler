from http import server
import discord
import datetime
import asyncio
import sys
from discord import app_commands
from discord.ext import tasks
import sqlite3
from database import check_user, check_request

from enum import Enum

class LogClass(Enum):
    SYSTEM = 1
    COMMAND = 2
    RESULT = 3
    ERROR = 4    

class CriticsGuildButler(discord.Client):   
    def __init__(self, *, db, server_ids, bot_id, log_channel_id, print_log=True):      
        intents = discord.Intents.default()
        intents.message_content = True

        self.db = db

        self.server_ids = server_ids
        self.bot_id = bot_id
        self.log_channel_id = log_channel_id

        self.print_log = print_log

        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.server_obj = None

    
    async def setup_hook(self):
        self.add_commands()

        # This copies the global commands over to the guilds.
        for server_id in self.server_ids:
            server = discord.Object(id=server_id)

            self.tree.copy_global_to(guild=server)
            await self.tree.sync(guild=server)

        # We consider the first server in the list to be The server and thus the one where new things will be generated.
        server_id = self.server_ids[0]
        self.server_obj = await self.fetch_guild(server_id)
        await self.server_obj.fetch_roles()

        self.log_channel_obj = await self.fetch_channel(self.log_channel_id)

        await self.log_system("Butler ready.")

        return

    async def send_channel(self, channel: discord.TextChannel, content = None, embeds = None, **kwargs):
        await channel.send(content=content, embeds=embeds, **kwargs)

    async def send_dm(self, user: discord.User, content = None, embeds = None, **kwargs):
        await user.send(content=content, embeds=embeds, **kwargs)

    async def send_thread(self, thread: discord.Thread, content = None, embeds = None, **kwargs):
        await thread.send(content=content, embeds=embeds, **kwargs)

    async def defer(self, interaction):
        await interaction.response.defer(ephemeral=True)

    async def send_response(self, interaction: discord.Interaction, content = None, **kwargs):
        await interaction.followup.send(content=content, ephemeral=True, **kwargs)

    async def send_reply(self, message: discord.Message, content = None, embeds = None, **kwargs):
        await message.reply(content=content, embeds=embeds, **kwargs)

    def get_class_icon(self, log_class):
        if log_class == LogClass.SYSTEM:
            return "🖥️"
        elif log_class == LogClass.COMMAND:
            return "👉"
        elif log_class == LogClass.RESULT:
            return "🔢"
        elif log_class == LogClass.ERROR:
            return "‼️"

        return ""

    # Returns the log id
    async def log(self, summary: str, user_id, request_id, log_class, cause_id, **kwargs):

        try:
            cursor = self.db.cursor()

            if not user_id is None:
                check_user(self.db, user_id)            

            if not request_id is None:
                if not check_request(self.db, request_id):
                    await self.log_system(f"Attempt to write log entry with request_id not present in the database: {request_id}",cause_id=None)
                    request_id = None

            timestamp = datetime.datetime.now()

            cursor.execute("INSERT INTO log (user_id, request_id, timestamp, class, cause_id, summary) VALUES (?,?,?,?,?,?)",(user_id, request_id, timestamp, log_class.value, cause_id, summary))
            log_id = cursor.lastrowid
        except sqlite3.Error as e:
            print(f"SQLite error when trying to insert into the database!!: {e}")
            await self.send_channel(self.log_channel_obj, content=f"IMPORTANT!! There was an error when trying to write the log message into the database. Please check.")            

        message = f"{self.get_class_icon(log_class)}{log_class.name}/{log_id} - {summary}"

        await self.send_channel(self.log_channel_obj, content=message, embeds=None, allowed_mentions=discord.AllowedMentions(users=[]),**kwargs)

        if self.print_log:
            print(f"{timestamp} - {message}")

        return log_id

    async def log_system(self, summary: str, cause_id=None, **kwargs):
        return await self.log(summary=summary,user_id=None,request_id=None,log_class=LogClass.SYSTEM,cause_id=cause_id,**kwargs)

    async def log_command(self, summary: str, user_id, request_id=None, **kwargs):
        return await self.log(summary=summary,user_id=user_id,request_id=request_id,log_class=LogClass.COMMAND,cause_id=None,**kwargs)

    async def log_result(self, summary: str, user_id, request_id=None, cause_id=None, **kwargs):
        return await self.log(summary=summary,user_id=user_id,request_id=request_id,cause_id=cause_id,**kwargs)

    async def log_error(self, summary: str, user_id, request_id=None, cause_id=None, **kwargs):
        return await self.log(summary=summary,user_id=user_id,request_id=request_id,cause_id=cause_id,**kwargs)

    def mention_user(self, user_id):
        return f"<@{user_id}>"

    def add_commands(self):
        @self.tree.command()
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def shutdown(interaction: discord.Interaction):
            await self.defer(interaction)

            user_mention = self.mention_user(interaction.user.id)
            command_id = await self.log_command(f"Received shutdown command from {user_mention}.",interaction.user.id)
            await self.send_response(interaction,'Shutting down... Bye!')
            await self.log_system("Shutting down.",cause_id=command_id)
            exit()        

