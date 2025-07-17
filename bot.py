from http import server
import discord
import datetime
import asyncio
import sys
from discord import app_commands
from discord.ext import tasks
import sqlite3
from database import check_user, check_request
import textwrap

from enum import Enum

class LogClass(Enum):
    SYSTEM = 1
    COMMAND = 2
    RESULT = 3
    ERROR = 4 
    
class RequestState(Enum):
    OPEN = 1
    CLAIMED = 2
    COMPLETED = 3
    CANCELLED = 4

class CriticsGuildButler(discord.Client):   
    def __init__(self, *, db_connect, server_ids, bot_id, log_channel_id, trusted_critic_role_id, print_log=True):      
        intents = discord.Intents.default()
        intents.message_content = True

        self.db_connect = db_connect

        self.server_ids = server_ids
        self.bot_id = bot_id
        self.log_channel_id = log_channel_id
        self.trusted_critic_role_id = trusted_critic_role_id

        self.print_log = print_log

        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.server_obj = None

    
    async def setup_hook(self):
        db = self.db_connect()

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

        await self.log_system(db,"Butler ready.")

        return

    ###
    # Logic and presentation synchronous functions
    ###

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

    def mention_user(self, user_id):
        return f"<@{user_id}>"

    # Use a negative number to show just the icon.
    def tokens(self, n):
        if n < 0:
            return f"🔹tokens"
        else:
            return f"{n}🔹tokens"

    def upvotes(self, n):
        if n < 0:
            return f"👍upvotes"
        else:
            return f"{n}👍upvotes"

    def stars(self, n):
        if n < 0:
            return f"⭐stars"
        else:
            return f"{n}⭐stars"

    def penalties(self, n):
        if n < 0:
            return f"🚫penalties"
        else:
            return f"{n}🚫penalties"

    def completed_critic_requests(self, n):
        if n < 0:
            return f"✔️completed critic requests"
        else:
            return f"{n}✔️completed critic requests"

    def completed_mapper_requests(self, n):
        if n < 0:
            return f"♻️completed mapper requests"
        else:
            return f"{n}♻️completed mapper requests"            

    ###
    # Discord / database logic and presentation methods
    ###

    async def display_request(self, thread_id):
        thread:discord.Thread = await self.fetch_channel(thread_id)

        # For now we just provide the link.
        return thread.jump_url


    ###
    # Interaction support methods
    ###
    async def send_channel(self, channel: discord.TextChannel, content = None, embeds = None, mentions = True, **kwargs):
        if not mentions:               
            await channel.send(content=content, embeds=embeds, allowed_mentions=discord.AllowedMentions(users=[]), **kwargs)
        else:
            await channel.send(content=content, embeds=embeds, **kwargs)

    async def send_dm(self, user: discord.User, content = None, embeds = None, mentions = False, **kwargs):
        if not mentions:
            await user.send(content=content, embeds=embeds, allowed_mentions=discord.AllowedMentions(users=[]), **kwargs)
        else:
            await user.send(content=content, embeds=embeds, **kwargs)

    async def send_thread(self, thread: discord.Thread, content = None, embeds = None, mentions = True, **kwargs):
        if not mentions:
            await thread.send(content=content, embeds=embeds, allowed_mentions=discord.AllowedMentions(users=[]), **kwargs)
        else:
            await thread.send(content=content, embeds=embeds, **kwargs)

    async def defer(self, interaction):
        await interaction.response.defer(ephemeral=True)

    async def send_response(self, interaction: discord.Interaction, content = None, mentions = False, **kwargs):
        if not mentions:
            await interaction.followup.send(content=content, ephemeral=True, allowed_mentions=discord.AllowedMentions(users=[]), **kwargs)
        else:
            await interaction.followup.send(content=content, ephemeral=True, **kwargs)

    async def send_reply(self, message: discord.Message, content = None, embeds = None, mentions = True, **kwargs):
        if not mentions:
            await message.reply(content=content, embeds=embeds, allowed_mentions=discord.AllowedMentions(users=[]), **kwargs)
        else:
            await message.reply(content=content, embeds=embeds, **kwargs)
    
    ###
    # Logging
    ###

    # Returns the log id
    async def log(self, db, summary: str, user_id, request_id, log_class, cause_id, **kwargs):

        try:
            cursor = db.cursor()

            if not user_id is None:
                check_user(db, user_id)            

            if not request_id is None:
                if not check_request(db, request_id):
                    await self.log_system(db, f"Attempt to write log entry with request_id not present in the database: {request_id}",cause_id=None)
                    request_id = None

            timestamp = datetime.datetime.now()

            cursor.execute("INSERT INTO log (user_id, request_id, timestamp, class, cause_id, summary) VALUES (?,?,?,?,?,?)",(user_id, request_id, timestamp, log_class.value, cause_id, summary))
            log_id = cursor.lastrowid
        except sqlite3.Error as e:
            print(f"SQLite error when trying to insert into the database!!: {e}")
            await self.send_channel(self.log_channel_obj, content=f"IMPORTANT!! There was an error when trying to write the log message into the database. Please check.")            

        message = f"{self.get_class_icon(log_class)}{log_class.name}/{log_id} - {summary}"

        await self.send_channel(self.log_channel_obj, content=message, embeds=None, mentions=False,**kwargs)

        if self.print_log:
            print(f"{timestamp} - {message}")

        return log_id

    async def log_system(self, db, summary: str, cause_id=None, **kwargs):
        return await self.log(db,summary,user_id=None,request_id=None,log_class=LogClass.SYSTEM,cause_id=cause_id,**kwargs)

    async def log_command(self, db, summary: str, user_id, request_id=None, **kwargs):
        return await self.log(db, summary,user_id=user_id,request_id=request_id,log_class=LogClass.COMMAND,cause_id=None,**kwargs)

    async def log_result(self, db, summary: str, user_id, request_id=None, cause_id=None, **kwargs):
        return await self.log(db, summary,user_id=user_id,request_id=request_id,cause_id=cause_id,**kwargs)

    async def log_error(self, db, summary: str, user_id, request_id=None, cause_id=None, **kwargs):
        return await self.log(db, summary,user_id=user_id,request_id=request_id,cause_id=cause_id,**kwargs)
    
    ###
    # Slash Commands
    ###
    def add_commands(self):
        ###
        # Admin
        ###

        @self.tree.command(description="(Admin only) Make the butler go offline.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def shutdown(interaction: discord.Interaction):
            await self.defer(interaction)
            db = self.db_connect()

            try:                
                user_mention = self.mention_user(interaction.user.id)
                command_id = await self.log_command(db,f"Received shutdown command from {user_mention}.",interaction.user.id)
                await self.send_response(interaction,'Shutting down... Bye!')
                await self.log_system(db,"Shutting down.",cause_id=command_id)
                await self.close()

                db.close()
                exit()
            except Exception as e:
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")

        @self.tree.command(description="(Admin only) Check user status")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user="User to check status")
        async def checkuser(interaction: discord.Interaction, user: discord.Member):
            await self.defer(interaction)
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} checked the status of {target_user_mention}.",interaction.user.id)

                check_user(db,user.id)

                cur = db.cursor()

                query = """
                    SELECT
                        u.tokens,
                        u.mapper_upvotes,
                        u.historic_mapper_upvotes,
                        u.critic_upvotes,
                        u.historic_critic_upvotes,
                        u.stars,
                        u.historic_stars,
                        u.penalties,
                        u.stakes,
                        u.completed_mapper_requests,
                        u.completed_critic_requests
                    FROM user u
                    WHERE u.user_id = ?
                    """
                res = cur.execute(query,(user.id,))
                (tokens,
                mapper_upvotes,
                historic_mapper_upvotes,
                critic_upvotes,
                historic_critic_upvotes,
                stars,
                historic_stars,
                penalties,
                stakes,
                completed_mapper_requests,
                completed_critic_requests) = res.fetchone()

                query_mapper_requests = """
                    SELECT
                        r.thread_id
                    FROM request r
                    WHERE r.author_id = :user_id AND r.state IN (:open, :claimed)
                    """
                data = {"user_id": user.id, "open": RequestState.OPEN.value, "claimed":RequestState.CLAIMED.value}
                res = cur.execute(query_mapper_requests,data)
                mapper_thread_ids = [r[0] for r in res.fetchall()]

                query_critic_requests = """
                    SELECT
                        r.thread_id
                    FROM request r
                    WHERE r.critic_id = :user_id AND r.state IN (:open, :claimed)
                    """
                data = {"user_id": user.id, "open": RequestState.OPEN.value, "claimed":RequestState.CLAIMED.value}
                res = cur.execute(query_critic_requests,data)
                critic_thread_ids = [r[0] for r in res.fetchall()]

                result = textwrap.dedent(f"""
                        {target_user_mention} status:

                        {self.tokens(tokens)}
                        {self.upvotes(mapper_upvotes)} (mapper)
                        {self.upvotes(historic_mapper_upvotes)} (mapper, historic)
                        {self.upvotes(critic_upvotes)} (critic)
                        {self.upvotes(historic_critic_upvotes)} (critic, historic)
                        {self.stars(stars)}
                        {self.stars(historic_stars)} (historic)
                        {self.penalties(penalties)}
                        {stakes} current stakes as critic
                        {completed_mapper_requests} completed mapper requests
                        {completed_critic_requests} completed critic requests

                    """)

                result += "Active mapper requests:\n\n"

                for mapper_thread_id in mapper_thread_ids:
                    thread_str = await self.display_request(mapper_thread_id)
                    result += f"{thread_str}\n"

                result += "\n"

                result += "Active critic requests:\n\n"

                for critic_thread_id in critic_thread_ids:
                    thread_str = await self.display_request(critic_thread_id)
                    result += f"{thread_str}\n"

                result += "\n"

                await self.send_response(interaction,result)
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()
        