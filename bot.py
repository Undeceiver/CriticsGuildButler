from http import server
from re import A
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

class RequestList(Enum):
    OPEN = 1
    CRITIC = 2
    TRUSTED_CRITIC = 3

class RequestType(Enum):
    PREVIEWER = 1
    BASIC_TESTPLAY = 2
    DETAILED_MOD = 3
    CURATABILITY = 4
    VERIFICATION = 5
    SS = 6
    BL = 7
    BPM = 8
    TIMING = 9
    PROFILE = 10
    FEEDBACK_ON_FEEDBACK = 11

class CriticsGuildButler(discord.Client):   
    def __init__(self, *, db_connect, 
                 server_ids, bot_id, 
                 log_channel_id, trusted_critic_role_id, 
                 open_list_channel_id, open_list_tag_ids, critic_list_channel_id, critic_list_tag_ids, trusted_critic_list_channel_id, trusted_critic_list_tag_ids, 
                 monthly_tokens, max_requests, max_penalties, 
                 print_log=True):      
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        self.db_connect = db_connect

        self.server_ids = server_ids
        self.bot_id = bot_id
        self.log_channel_id = log_channel_id
        self.trusted_critic_role_id = trusted_critic_role_id
        self.open_list_channel_id = open_list_channel_id
        self.open_list_tag_ids = open_list_tag_ids
        self.critic_list_channel_id = critic_list_channel_id
        self.critic_list_tag_ids = critic_list_tag_ids
        self.trusted_critic_list_channel_id = trusted_critic_list_channel_id
        self.trusted_critic_list_tag_ids = trusted_critic_list_tag_ids

        self.monthly_tokens = monthly_tokens
        self.max_requests = max_requests
        self.max_penalties = max_penalties

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
        self.trusted_critic_role_obj = await self.server_obj.fetch_role(self.trusted_critic_role_id)

        await self.log_system(db,"Butler ready.")

        return

    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id == self.open_list_channel_id:
            await self.newopenrequest(thread)
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

    async def update_tokens(self, db, user_id, update_fun, request_id = None, cause_id = None, **kwargs):
        cur = db.cursor()

        query = """
            SELECT
                u.tokens
            FROM user u
            WHERE u.user_id = ?
            """
        res = cur.execute(query,(user_id,))
        previous_tokens = res.fetchone()[0]

        new_tokens = update_fun(previous_tokens)

        query_update = """
            UPDATE user
            SET tokens = :tokens
            WHERE user_id = :user_id
        """
        data = {"tokens":new_tokens, "user_id":user_id}
        cur.execute(query_update,data)

        await self.log_tokens(db, user_id, previous_tokens, new_tokens, request_id, cause_id, **kwargs)

        return (previous_tokens,new_tokens)

    async def update_stars(self, db, user_id, update_fun, request_id = None, cause_id = None, update_historic=True, **kwargs):
        cur = db.cursor()

        query = """
            SELECT
                u.stars,
                u.historic_stars
            FROM user u
            WHERE u.user_id = ?
            """
        res = cur.execute(query,(user_id,))
        (previous_stars, previous_historic_stars) = res.fetchone()        

        new_stars = update_fun(previous_stars)

        if update_historic:
            diff_stars = new_stars - previous_stars
            new_historic_stars = previous_historic_stars + diff_stars

            query_update = """
                UPDATE user
                SET stars = :stars, historic_stars = :historic_stars
                WHERE user_id = :user_id
            """
            data = {"stars":new_stars, "historic_stars":new_historic_stars, "user_id":user_id}
            cur.execute(query_update,data)
        else:
            query_update = """
                UPDATE user
                SET stars = :stars
                WHERE user_id = :user_id
            """
            data = {"stars":new_stars, "user_id":user_id}
            cur.execute(query_update,data)

        await self.log_stars(db, user_id, previous_stars, new_stars, request_id, cause_id, **kwargs)

        return (previous_stars,new_stars)

    async def update_mapper_upvotes(self, db, user_id, update_fun, request_id = None, cause_id = None, update_historic=True, **kwargs):
        cur = db.cursor()

        query = """
            SELECT
                u.mapper_upvotes,
                u.historic_mapper_upvotes
            FROM user u
            WHERE u.user_id = ?
            """
        res = cur.execute(query,(user_id,))
        (previous_upvotes, previous_historic_upvotes) = res.fetchone()        

        new_upvotes = update_fun(previous_upvotes)

        if update_historic:
            diff_upvotes = new_upvotes - previous_upvotes
            new_historic_upvotes = previous_historic_upvotes + diff_upvotes

            query_update = """
                UPDATE user
                SET mapper_upvotes = :upvotes, historic_mapper_upvotes = :historic_upvotes
                WHERE user_id = :user_id
            """
            data = {"upvotes":new_upvotes, "historic_upvotes":new_historic_upvotes, "user_id":user_id}
            cur.execute(query_update,data)
        else:
            query_update = """
                UPDATE user
                SET mapper_upvotes = :upvotes
                WHERE user_id = :user_id
            """
            data = {"upvotes":new_upvotes, "user_id":user_id}
            cur.execute(query_update,data)

        await self.log_mapper_upvotes(db, user_id, previous_upvotes, new_upvotes, request_id, cause_id, **kwargs)

        return (previous_upvotes,new_upvotes)

    async def update_critic_upvotes(self, db, user_id, update_fun, request_id = None, cause_id = None, update_historic=True, **kwargs):
        cur = db.cursor()

        query = """
            SELECT
                u.critic_upvotes,
                u.historic_critic_upvotes
            FROM user u
            WHERE u.user_id = ?
            """
        res = cur.execute(query,(user_id,))
        (previous_upvotes, previous_historic_upvotes) = res.fetchone()        

        new_upvotes = update_fun(previous_upvotes)

        if update_historic:
            diff_upvotes = new_upvotes - previous_upvotes
            new_historic_upvotes = previous_historic_upvotes + diff_upvotes

            query_update = """
                UPDATE user
                SET critic_upvotes = :upvotes, historic_critic_upvotes = :historic_upvotes
                WHERE user_id = :user_id
            """
            data = {"upvotes":new_upvotes, "historic_upvotes":new_historic_upvotes, "user_id":user_id}
            cur.execute(query_update,data)
        else:
            query_update = """
                UPDATE user
                SET critic_upvotes = :upvotes
                WHERE user_id = :user_id
            """
            data = {"upvotes":new_upvotes, "user_id":user_id}
            cur.execute(query_update,data)

        await self.log_critic_upvotes(db, user_id, previous_upvotes, new_upvotes, request_id, cause_id, **kwargs)

        return (previous_upvotes,new_upvotes)

    async def update_penalties(self, db, user_id, update_fun, request_id = None, cause_id = None, **kwargs):
        cur = db.cursor()

        query = """
            SELECT
                u.penalties
            FROM user u
            WHERE u.user_id = ?
            """
        res = cur.execute(query,(user_id,))
        previous_penalties = res.fetchone()[0]

        new_penalties = update_fun(previous_penalties)

        query_update = """
            UPDATE user
            SET penalties = :penalties
            WHERE user_id = :user_id
        """
        data = {"penalties":new_penalties, "user_id":user_id}
        cur.execute(query_update,data)

        await self.log_penalties(db, user_id, previous_penalties, new_penalties, request_id, cause_id, **kwargs)

        return (previous_penalties,new_penalties)    

    async def create_request(self, db, thread: discord.Thread, cause_id=None):
        thread_id = thread.id
        author_id = thread.owner_id

        # We assume there is exactly one tag. Do not call this function unless this is checked
        tag = thread.applied_tags[0]      
        request_type = None
        if thread.parent_id == self.open_list_channel_id:
            list_option = RequestList.OPEN            
            for i in range(len(self.open_list_tag_ids)):
                if tag.id == self.open_list_tag_ids[i]:
                    request_type = RequestType(i+1)
        elif thread.parent_id == self.critic_list_channel_id:
            list_option = RequestList.CRITIC
            for i in range(len(self.critic_list_tag_ids)):
                if tag.id == self.critic_list_tag_ids[i]:
                    request_type = RequestType(i+1)
        elif thread.parent_id == self.trusted_critic_list_channel_id:
            list_option = RequestList.TRUSTED_CRITIC
            for i in range(len(self.trusted_critic_list_tag_ids)):
                if tag.id == self.trusted_critic_list_tag_ids[i]:
                    request_type = RequestType(i+1)
        else:
            await self.log_system(db, f"Unexpected forum thread encountered when creating new request: {thread.parent_id}",cause_id=cause_id)       
            return None

        if request_type is None:
            await self.log_system(db, f"Unexpected request type encountered on {list_option}: {tag.id} with label {tag.name}.",cause_id=cause_id)
            return None

        cur = db.cursor()

        query_create = """
            INSERT INTO request
            (thread_id, author_id, list, critic_id, type, state)
            VALUES
            (:thread_id, :author_id, :list, NULL, :type, :open_state)
            """
        data = {"thread_id":thread_id, "author_id":author_id, "list":list_option.value, "type":request_type.value, "open_state":RequestState.OPEN.value}
        cur.execute(query_create,data)

        user_mention = self.mention_user(thread.owner_id)        
        await self.log_result(db,f"{user_mention} created request {thread.jump_url} of {request_type} in {list_option}.",thread.owner_id,request_id=thread_id,cause_id=cause_id)

        return thread_id

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

    async def check_admin_channel(self, interaction: discord.Interaction):
        if interaction.channel_id != self.log_channel_id:
            response = f"This command can only be run in {self.log_channel_obj.jump_url}."
            await self.send_response(interaction, response)
            return False
        else:
            return True

    async def send_admin_channel(self, content = None, embeds = None, mentions = False, **kwargs):
        return await self.send_channel(self.log_channel_obj, content, embeds, mentions, **kwargs)    
    
    async def check_trusted_critic(self, db, interaction: discord.Interaction, command_name, request_id = None, cause_id = None, **kwargs):
        if not any(role.id == self.trusted_critic_role_id for role in interaction.user.roles):
            user_mention = self.mention_user(interaction.user.id)
            await self.log_error(db, f"{user_mention} tried to run {command_name} but they are not a trusted critic.",user_id=interaction.user.id, request_id=request_id, cause_id=cause_id, **kwargs)
            await self.send_response(interaction, "Only trusted critics can use this command.")
            return False
        else:
            return True

    async def check_request_owner(self, db, interaction: discord.Interaction, command_name, cause_id = None, **kwargs):
        thread_id = interaction.channel_id
        channel_obj = await self.server_obj.fetch_channel(thread_id)

        user_mention = self.mention_user(interaction.user.id)

        if not isinstance(channel_obj,discord.Thread):            
            await self.log_error(db, f"{user_mention} tried to run {command_name} outside a thread.",interaction.user.id,cause_id=cause_id)
            await self.send_response(interaction, "This command can only be run in a Critic's Guild request you created.")
            return False

        if not check_request(db, thread_id):
            await self.log_error(db, f"{user_mention} tried to run {command_name} in a thread not present in the database.",interaction.user.id,cause_id=cause_id)
            await self.send_response(interaction, "This command can only be run in a Critic's Guild request you created.")
            return False
        
        cur = db.cursor()

        if not any(role.id == self.trusted_critic_role_id for role in interaction.user.roles):
            query_owner = """
                SELECT r.author_id
                FROM request r
                WHERE r.thread_id = ?
                """
            res = cur.execute(query_owner,(thread_id,))
            author_id = res.fetchone()[0]

            if author_id != interaction.user.id:
                await self.log_error(db, f"{user_mention} tried to run {command_name} in a request they did not author.",interaction.user.id,cause_id=cause_id)
                await self.send_response(interaction, "You cannot run this command because you do not own this request.")
                return False

        return True
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

            timestamp = datetime.datetime.now(tz = None)

            cursor.execute("INSERT INTO log (user_id, request_id, timestamp, class, cause_id, summary) VALUES (?,?,?,?,?,?)",(user_id, request_id, timestamp, log_class.value, cause_id, summary))
            log_id = cursor.lastrowid
        except sqlite3.Error as e:
            print(f"SQLite error when trying to insert into the database!!: {e}")
            await self.send_admin_channel(content=f"IMPORTANT!! There was an error when trying to write the log message into the database. Please check.")            

        message = f"{self.get_class_icon(log_class)}{log_class.name}/{log_id} - {summary}"

        await self.send_admin_channel(content=message,**kwargs)

        if self.print_log:
            print(f"{timestamp} - {message}")

        return log_id

    async def log_system(self, db, summary: str, cause_id=None, **kwargs):
        return await self.log(db,summary,user_id=None,request_id=None,log_class=LogClass.SYSTEM,cause_id=cause_id,**kwargs)

    async def log_command(self, db, summary: str, user_id, request_id=None, **kwargs):
        return await self.log(db, summary,user_id=user_id,request_id=request_id,log_class=LogClass.COMMAND,cause_id=None,**kwargs)

    async def log_result(self, db, summary: str, user_id, request_id=None, cause_id=None, **kwargs):
        return await self.log(db, summary,user_id=user_id,request_id=request_id,log_class=LogClass.RESULT,cause_id=cause_id,**kwargs)

    async def log_error(self, db, summary: str, user_id, request_id=None, cause_id=None, **kwargs):
        return await self.log(db, summary,user_id=user_id,request_id=request_id,log_class=LogClass.ERROR,cause_id=cause_id,**kwargs)
    
    async def log_tokens(self, db, user_id, previous_tokens, new_tokens, request_id=None, cause_id=None, **kwargs):
        user_mention = self.mention_user(user_id)
        return await self.log_result(db,f"{user_mention} went from {self.tokens(previous_tokens)} to {self.tokens(new_tokens)}.",user_id,request_id,cause_id,**kwargs)

    async def log_mapper_upvotes(self, db, user_id, previous_upvotes, new_upvotes, request_id=None, cause_id=None, **kwargs):
        user_mention = self.mention_user(user_id)
        return await self.log_result(db,f"{user_mention} went from {self.upvotes(previous_upvotes)} to {self.upvotes(new_upvotes)} (mapper).",user_id,request_id,cause_id,**kwargs)

    async def log_critic_upvotes(self, db, user_id, previous_upvotes, new_upvotes, request_id=None, cause_id=None, **kwargs):
        user_mention = self.mention_user(user_id)
        return await self.log_result(db,f"{user_mention} went from {self.upvotes(previous_upvotes)} to {self.upvotes(new_upvotes)} (critic).",user_id,request_id,cause_id,**kwargs)

    async def log_stars(self, db, user_id, previous_stars, new_stars, request_id=None, cause_id=None, **kwargs):
        user_mention = self.mention_user(user_id)
        return await self.log_result(db,f"{user_mention} went from {self.stars(previous_stars)} to {self.stars(new_stars)}.",user_id,request_id,cause_id,**kwargs)

    async def log_penalties(self, db, user_id, previous_penalties, new_penalties, request_id=None, cause_id=None, **kwargs):
        user_mention = self.mention_user(user_id)
        return await self.log_result(db,f"{user_mention} went from {self.penalties(previous_penalties)} to {self.penalties(new_penalties)}.",user_id,request_id,cause_id,**kwargs)

    ###
    # Reactions to events
    ###
    async def newopenrequest(self, thread: discord.Thread):
        db = self.db_connect()

        try:
            user_mention = self.mention_user(thread.owner_id)
            request_title = thread.name
            command_id = await self.log_command(db,f"{user_mention} created request {thread.jump_url} in the open list.",thread.owner_id)
            
            check_user(db,thread.owner_id)

            cur = db.cursor()

            # Check exactly one tag
            n_tags = len(thread.applied_tags)
            if n_tags != 1:
                await self.log_error(db,f"{user_mention} tried to create a new request with {n_tags} tags applied to it.",thread.owner_id,cause_id=command_id)
                user = await self.server_obj.fetch_member(thread.owner_id)
                await self.send_dm(user,f"Your request \"{request_title}\" was deleted because it had {n_tags} tags applied to it. Requests must have exactly 1 tag to be valid, indicating the type of request they are.")
                await thread.delete()
                db.close()
                return

            # Check it has attachment - This is not a requirement but if it does not it is noted on the bot's message.
            if not thread.last_message_id is None:
                message = await thread.fetch_message(thread.last_message_id)
                has_attachment = (len(message.attachments) > 0)
            else:
                await self.log_system(db,f"Couldn't fetch the last message on a thread.",cause_id=command_id)
                has_attachment = True

            # No token requirement

            # Check number of penalties
            query_penalties = """
                SELECT u.penalties
                FROM user u
                WHERE u.user_id = ?
                """
            res = cur.execute(query_penalties,(thread.owner_id,))
            penalties = res.fetchone()[0]

            if penalties >= self.max_penalties:
                await self.log_error(db,f"{user_mention} tried to create a new request but they have {self.penalties(penalties)}",thread.owner_id,cause_id=command_id)
                user = await self.server_obj.fetch_member(thread.owner_id)
                await self.send_dm(user,f"Your request \"{request_title}\" was deleted because you have {self.penalties(penalties)}. You are not allowed to create requests with these many penalties. If you would like to have penalties removed, contact Staff to understand the reason you received them.")
                await thread.delete()
                db.close()
                return

            # Check number of active requests
            query_active = """
                SELECT
                    COUNT(*)
                FROM request r
                WHERE r.author_id = :user_id
                    AND r.state IN (:open_state,:claimed_state)
                """
            data = {"user_id":thread.owner_id, "open_state":RequestState.OPEN.value,"claimed_state":RequestState.CLAIMED.value}
            res = cur.execute(query_active,data)
            requests = res.fetchone()[0]
            
            if requests >= self.max_requests:
                await self.log_error(db,f"{user_mention} tried to create a new request but they already have {requests} requests open.",thread.owner_id,cause_id=command_id)
                user = await self.server_obj.fetch_member(thread.owner_id)
                await self.send_dm(user,f"Your request \"{request_title}\" was deleted because you already have {requests} requests open. You may not have more than {self.max_requests} requests open at any one time (across all lists). Please wait until one of your requests is completed or cancel an unclaimed request.")
                await thread.delete()
                db.close()
                return    

            # Create the request
            thread_id = await self.create_request(db,thread,cause_id=command_id)
            
            # Make a post in the request with basic info.
            await self.send_thread(thread, f"✅The {thread.applied_tags[0].emoji.name}**{thread.applied_tags[0].name}** request has been registered. {user_mention} now has {requests+1}/{self.max_requests} active requests.",mentions=False)
            await self.send_thread(thread, f"Requests cannot be reserved in the open list, but anybody may express their interest in responding to this request.",mentions=False)
            await self.send_thread(thread, f"❌{user_mention} may cancel the request if nobody has responded to it by using `/cancelrequest`.",mentions=False)
            if not has_attachment:
                await self.send_thread(thread,f"⚠️No attachment was detected on the original message. If this is a mistake, please remember to attach your map file now. Ignore if attachment isn't necessary.",mentions=False)

        except Exception as e:                
            await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
        db.close()

    ###
    # Slash Commands
    ###
    def add_commands(self):
        ###
        # All users
        ###
        @self.tree.command(description=f"Claim your monthly {self.tokens(self.monthly_tokens)}.")
        async def claimtokens(interaction: discord.Interaction):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                command_id = await self.log_command(db,f"{user_mention} claimed monthly tokens.",interaction.user.id)

                check_user(db,interaction.user.id)

                cur = db.cursor()

                query_check_claimed = """
                    SELECT
                        u.claimed_tokens
                    FROM user u
                    WHERE u.user_id = ?
                """
                res = cur.execute(query_check_claimed,(interaction.user.id,))
                claimed_tokens = res.fetchone()[0]

                if claimed_tokens != 0:
                    await self.log_error(db, summary=f"{user_mention} tried to claim {self.tokens(self.monthly_tokens)} more than once this month.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction,content=f"You have already claimed your {self.tokens(self.monthly_tokens)} this month. Please wait until the end of the month to claim again.")                    
                else:
                    query_set_claimed = """
                        UPDATE user
                        SET claimed_tokens = 1
                        WHERE user_id = ?
                    """
                    res = cur.execute(query_set_claimed,(interaction.user.id,))

                    def claim_tokens_fun(previous):
                        return previous + self.monthly_tokens

                    (previous_tokens, new_tokens) = await self.update_tokens(db,interaction.user.id,claim_tokens_fun,cause_id=command_id)

                    await self.send_response(interaction, f"You have claimed your monthly {self.tokens(self.monthly_tokens)}, and now have {self.tokens(new_tokens)} in total.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"Gift some of your {self.tokens(-1)} to another user.")
        @app_commands.describe(user=f"User to gift {self.tokens(-1)} to.", tokens=f"Number of {self.tokens(-1)} to gift.")
        async def gifttokens(interaction: discord.Interaction, user: discord.Member, tokens: int):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} gifted {self.tokens(tokens)} to {target_user_mention}.",interaction.user.id)

                check_user(db,interaction.user.id)
                check_user(db,user.id)

                if user.id == interaction.user.id:
                    await self.log_error(db, summary=f"{user_mention} tried to gift {self.tokens(tokens)} to themselves.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction,f"You cannot gift {self.tokens(-1)} to yourself!")
                    db.close()
                    return
                cur = db.cursor()

                if tokens <= 0:
                    await self.log_error(db, summary=f"{user_mention} tried to gift {self.tokens(0)}.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction,f"Please introduce a positive amount of {self.tokens(-1)} to gift.")
                    db.close()
                    return

                query_available_tokens = """
                    SELECT
                        u.tokens
                    FROM user u
                    WHERE u.user_id = ?
                """
                res = cur.execute(query_available_tokens,(interaction.user.id,))
                available_tokens = res.fetchone()[0]

                if available_tokens < tokens:
                    await self.log_error(db, summary=f"{user_mention} tried to gift {self.tokens(tokens)} to {target_user_mention} but they only had {self.tokens(available_tokens)} available.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction,content=f"You only have {self.tokens(available_tokens)}.")                    
                    db.close()
                    return
                
                def reduce_tokens_fun(previous):
                    return previous - tokens

                def increase_tokens_fun(previous):
                    return previous + tokens

                (previous_self_tokens, new_self_tokens) = await self.update_tokens(db,interaction.user.id,reduce_tokens_fun,cause_id=command_id)
                (previous_other_tokens, new_other_tokens) = await self.update_tokens(db,user.id,increase_tokens_fun,cause_id=command_id)

                await self.send_response(interaction, f"You gifted {self.tokens(tokens)} to {target_user_mention}, and now have {self.tokens(new_self_tokens)} left. Very kind of you!")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"Check how many {self.tokens(-1)} you have.")
        async def checktokens(interaction: discord.Interaction):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                command_id = await self.log_command(db,f"{user_mention} checked their {self.tokens(-1)}",interaction.user.id)

                check_user(db,interaction.user.id)

                cur = db.cursor()

                query_check_tokens = """
                    SELECT
                        u.tokens,
                        u.claimed_tokens
                    FROM user u
                    WHERE u.user_id = ?
                """
                res = cur.execute(query_check_tokens,(interaction.user.id,))
                (tokens,claimed) = res.fetchone()
                
                if claimed != 0:
                    await self.send_response(interaction, f"You have {self.tokens(tokens)}.")
                else:
                    await self.send_response(interaction, f"You have {self.tokens(tokens)}, but you can claim your monthly {self.tokens(self.monthly_tokens)} by using /claimtokens.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"Check how many {self.penalties(-1)} you have.")
        async def checkpenalties(interaction: discord.Interaction):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                command_id = await self.log_command(db,f"{user_mention} checked their {self.penalties(-1)}",interaction.user.id)

                check_user(db,interaction.user.id)

                cur = db.cursor()

                query_check_penalties = """
                    SELECT
                        u.penalties
                    FROM user u
                    WHERE u.user_id = ?
                """
                res = cur.execute(query_check_penalties,(interaction.user.id,))
                penalties = res.fetchone()[0]
                
                await self.send_response(interaction, f"You have {self.penalties(penalties)}.")                
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"Cancel this request.")
        @app_commands.describe(reason=f"Reason for canceling.")
        async def cancelrequest(interaction: discord.Interaction, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                channel_obj = await self.server_obj.fetch_channel(interaction.channel_id)
                command_id = await self.log_command(db,f"{user_mention} attempted to cancel {channel_obj.jump_url} with reason: {reason}.",interaction.user.id)

                if not await self.check_request_owner(db, interaction, command_name="/cancelrequest", cause_id = command_id):
                    db.close()
                    return

                cur = db.cursor()

                thread_id = interaction.channel_id

                # Check the state of the request
                query_state = """
                    SELECT r.state
                    FROM request r
                    WHERE r.thread_id = ?
                    """
                res = cur.execute(query_state,(thread_id,))
                state_id = res.fetchone()[0]                
                state = RequestState(state_id)

                if state != RequestState.OPEN:
                    await self.log_error(db, f"{user_mention} tried to cancel {channel_obj.jump_url} but the request is not in open state.",interaction.user_id,request_id=thread_id,cause_id=command_id)
                    await self.send_response(interaction, f"You cannot cancel this request because it is not in open state and/or it has been claimed by a critic.")
                    db.close()
                    return

                # Change state. There should be no critic stake (it wouldn't be cancellable)
                query_update = """
                    UPDATE request
                    SET state = :cancelled_state
                    WHERE thread_id = :thread_id
                    """
                data = {"cancelled_state":RequestState.CANCELLED.value,"thread_id":thread_id}
                res = cur.execute(query_update,data)
                
                # Return tokens
                # TODO               
                tokens_returned_str = ""
                
                # Lock the thread
                await self.send_thread(channel_obj, f"{user_mention} cancelled this request. {tokens_returned_str}",mentions=False)
                await channel_obj.edit(locked=True,archived=True)
                
                await self.log_result(db,f"{user_mention} cancelled {channel_obj.jump_url} with reason: {reason}",interaction.user.id,request_id=thread_id,cause_id=command_id)
                                
                await self.send_response(interaction, f"The request was cancelled.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        ###
        # Trusted critics
        ###
        
        @self.tree.command(description=f"(Trusted critics only) Reward {self.tokens(-1)} to a user for good participation in the guild.")
        @app_commands.describe(user=f"User to reward {self.tokens(-1)} to.", tokens=f"Number of {self.tokens(-1)} to reward.", reason=f"Justification for the reward.")
        async def rewardtokens(interaction: discord.Interaction, user: discord.Member, tokens: int, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()            

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} rewarded {target_user_mention} {self.tokens(tokens)} with reason: {reason}.",interaction.user.id)

                if not await self.check_trusted_critic(db, interaction, command_name="/rewardtokens", cause_id = command_id):
                    db.close()
                    return

                if not check_user(db,user.id,create=False):
                    await self.log_error(db, summary=f"{target_user_mention} cannot be rewarded {self.tokens(-1)} because they have never interacted with the bot before.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction, f"{target_user_mention} cannot be rewarded {self.tokens(-1)} because they have never interacted with the bot before. This is an intentional limitation. Please do not reward users unless they have participated in the guild before.")
                    db.close()
                    return
                
                if tokens <= 0:
                    await self.log_error(db, summary=f"{user_mention} tried to reward {self.tokens(0)}.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction,f"Please introduce a positive amount of {self.tokens(-1)} to reward.")
                    db.close()
                    return                
                                
                def increase_tokens_fun(previous):
                    return previous + tokens

                (previous_tokens, new_tokens) = await self.update_tokens(db,user.id,increase_tokens_fun,cause_id=command_id)

                await self.send_response(interaction, f"You rewarded {target_user_mention} {self.tokens(tokens)}.")
                await self.send_dm(user, f"A trusted critic rewarded you {self.tokens(tokens)} and you now have {self.tokens(new_tokens)} in total. Reason: {reason}")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Trusted critics only) Reward {self.stars(1)} to a user for giving good mapping feedback.")
        @app_commands.describe(user=f"User to reward {self.stars(1)} to.", reason=f"Justification for the reward.")
        async def rewardstar(interaction: discord.Interaction, user: discord.Member, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()            

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} rewarded {target_user_mention} {self.stars(1)} with reason: {reason}.",interaction.user.id)

                if not await self.check_trusted_critic(db, interaction, command_name="/rewardstar", cause_id = command_id):
                    db.close()
                    return                
                
                if not check_user(db,user.id,create=False):
                    await self.log_error(db, summary=f"{target_user_mention} cannot be rewarded {self.stars(1)} because they have never interacted with the bot before.", user_id=interaction.user.id,cause_id=command_id)
                    await self.send_response(interaction, f"{target_user_mention} cannot be rewarded {self.stars(1)} because they have never interacted with the bot before. This is an intentional limitation. Please do not reward users unless they have participated in the guild before.")
                    db.close()
                    return
                                
                def increase_stars_fun(previous):
                    return previous + 1

                (previous_stars, new_stars) = await self.update_stars(db,user.id,increase_stars_fun,cause_id=command_id)

                await self.send_response(interaction, f"You rewarded {target_user_mention} {self.stars(1)}.")                
                await self.send_dm(user, f"A trusted critic rewarded you {self.stars(1)} with reason: {reason}")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        ###
        # Admin
        ###

        @self.tree.command(description="(Admin only) Check if the butler is online.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def ping(interaction: discord.Interaction):
            await self.defer(interaction)
            await self.send_response(interaction,"Pong.")

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

        @self.tree.command(description="(Admin only) Check user status.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user="User to check status.")
        async def checkuser(interaction: discord.Interaction, user: discord.Member):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

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

                await self.send_admin_channel(result)

                if len(mapper_thread_ids) > 0:                    
                    await self.send_admin_channel("Active mapper requests:")                              

                    for mapper_thread_id in mapper_thread_ids:
                        thread_str = await self.display_request(mapper_thread_id)
                        await self.send_admin_channel(thread_str)
                else:
                    await self.send_admin_channel("No active mapper requests.")                
                
                if len(critic_thread_ids) > 0:
                    await self.send_admin_channel("Active critic requests:")

                    for critic_thread_id in critic_thread_ids:
                        thread_str = await self.display_request(critic_thread_id)
                        result += f"{thread_str}\n"
                else:
                    await self.send_admin_channel("No active critic requests")    
                
                await self.send_response(interaction,"Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description="(Admin only) Check user log.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user="User to check log.", days="Number of past days to check the log for.", max_messages="Maximum number of log messages to print.", with_tree="Include causal tree of command (causes and effects).", commands="Include commands.", results="Include results.", errors="Include errors.")
        async def checkuserlog(interaction: discord.Interaction, user: discord.Member, days:int = 1, max_messages:int = 10, with_tree:bool = False, commands:bool = True, results:bool = True, errors:bool = True):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} checked the log for {target_user_mention} (past {days} days, maximum of {max_messages} entries).",interaction.user.id)

                check_user(db,user.id)

                cur = db.cursor()

                query = """
                    SELECT
                        l.log_id,
                        l.request_id,
                        datetime(l.timestamp),
                        l.class,
                        l.cause_id,
                        l.summary
                    FROM log l
                    WHERE
                        l.user_id = :user_id AND (julianday('now') - julianday(l.timestamp)) < :days
                        AND (
                            (:commands AND l.class = :command_class) OR
                            (:results AND l.class = :result_class) OR
                            (:errors AND l.class = :error_class)
                        )
                    ORDER BY l.timestamp DESC
                    LIMIT :max_messages
                    """
                data = {"user_id":user.id, "days": days, "commands": commands, "command_class": LogClass.COMMAND.value, "results": results, "result_class": LogClass.RESULT.value, "errors": errors, "error_class":LogClass.ERROR.value, "max_messages":max_messages}
                res = cur.execute(query,data)
                logs = res.fetchall()
                logs.reverse()

                async def log_message(log,with_cause=with_tree,with_consequences=with_tree,prefix=""):
                    (log_id, request_id, date_str, log_class_id, cause_id, summary) = log
                    log_class = LogClass(log_class_id)                    

                    message = f"{prefix}{self.get_class_icon(log_class)}{log_class.name}/{log_id} ({date_str}) - {summary}"

                    if not request_id is None:
                        thread_str = await self.display_request(request_id)
                        message += f" (on {thread_str})"

                    await self.send_admin_channel(message)

                    if with_cause:
                        query_cause = """
                            SELECT
                                l.log_id,
                                l.request_id,
                                datetime(l.timestamp),
                                l.class,
                                l.cause_id,
                                l.summary
                            FROM log l
                            WHERE
                                l.log_id = ?
                            """
                        res = cur.execute(query_cause,(cause_id,))
                        log = res.fetchone()

                        if log:
                            await log_message(log,with_cause=True,with_consequences=False,prefix="caused by ")

                    if with_consequences:
                        query_consequences = """
                            SELECT
                                l.log_id,
                                l.request_id,
                                datetime(l.timestamp),
                                l.class,
                                l.cause_id,
                                l.summary
                            FROM log l
                            WHERE
                                l.cause_id = ?
                            """
                        res = cur.execute(query_consequences,(log_id,))
                        logs = res.fetchall()

                        for log in logs:
                            await log_message(log,with_cause=False,with_consequences=True,prefix="with consequence ")
                                
                for log in logs:
                    await log_message(log)                    

                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description="(Admin only) Check system log.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(days="Number of past days to check the log for.", max_messages="Maximum number of log messages to print.", with_tree="Include causal tree of command (causes and effects).")
        async def checksystemlog(interaction: discord.Interaction, days:int = 1, max_messages:int = 10, with_tree:bool = True):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                command_id = await self.log_command(db,f"{user_mention} checked the system log (past {days} days, maximum of {max_messages} entries).",interaction.user.id)
                
                cur = db.cursor()

                query = """
                    SELECT
                        l.log_id,
                        l.request_id,
                        datetime(l.timestamp),
                        l.class,
                        l.cause_id,
                        l.summary
                    FROM log l
                    WHERE
                        (julianday('now') - julianday(l.timestamp)) < :days
                        AND l.class = :system_class
                    ORDER BY l.timestamp DESC
                    LIMIT :max_messages
                    """
                data = {"days": days, "system_class":LogClass.SYSTEM.value, "max_messages":max_messages}
                res = cur.execute(query,data)
                logs = res.fetchall()
                logs.reverse()

                async def log_message(log,with_cause=with_tree,with_consequences=with_tree,prefix=""):
                    (log_id, request_id, date_str, log_class_id, cause_id, summary) = log
                    log_class = LogClass(log_class_id)                    

                    message = f"{prefix}{self.get_class_icon(log_class)}{log_class.name}/{log_id} ({date_str}) - {summary}"

                    if not request_id is None:
                        thread_str = await self.display_request(request_id)
                        message += f" (on {thread_str})"

                    await self.send_admin_channel(message)

                    if with_cause:
                        query_cause = """
                            SELECT
                                l.log_id,
                                l.request_id,
                                datetime(l.timestamp),
                                l.class,
                                l.cause_id,
                                l.summary
                            FROM log l
                            WHERE
                                l.log_id = ?
                            """
                        res = cur.execute(query_cause,(cause_id,))
                        log = res.fetchone()

                        if log:
                            await log_message(log,with_cause=True,with_consequences=False,prefix="caused by ")

                    if with_consequences:
                        query_consequences = """
                            SELECT
                                l.log_id,
                                l.request_id,
                                datetime(l.timestamp),
                                l.class,
                                l.cause_id,
                                l.summary
                            FROM log l
                            WHERE
                                l.cause_id = ?
                            """
                        res = cur.execute(query_consequences,(log_id,))
                        logs = res.fetchall()

                        for log in logs:
                            await log_message(log,with_cause=False,with_consequences=True,prefix="with consequence ")
                                
                for log in logs:
                    await log_message(log)                    

                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Set {self.tokens(-1)} count of user.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user=f"User to set {self.tokens(-1)} for.", tokens=f"New number of {self.tokens(-1)}.", reason=f"Justification.")
        async def settokens(interaction: discord.Interaction, user: discord.Member, tokens: int, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} set {target_user_mention} to {self.tokens(tokens)} with reason: {reason}.",interaction.user.id)

                check_user(db,user.id)

                def set_tokens_fun(previous):
                    return tokens

                (previous_tokens, new_tokens) = await self.update_tokens(db,user.id,set_tokens_fun,cause_id=command_id)

                await self.send_response(interaction, f"Tokens for {target_user_mention} set from {self.tokens(previous_tokens)} to {self.tokens(new_tokens)}.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Set {self.stars(-1)} count of user.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user=f"User to set {self.stars(-1)} for.", stars=f"New number of {self.stars(-1)}.", reason=f"Justification.")
        async def setstars(interaction: discord.Interaction, user: discord.Member, stars: int, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} set {target_user_mention} to {self.stars(stars)} with reason: {reason}.",interaction.user.id)

                check_user(db,user.id)

                def set_stars_fun(previous):
                    return stars

                (previous_stars, new_stars) = await self.update_stars(db,user.id,set_stars_fun,cause_id=command_id)

                await self.send_response(interaction, f"Stars for {target_user_mention} set from {self.stars(previous_stars)} to {self.stars(new_stars)}.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Set {self.upvotes(-1)} count of mapper.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user=f"Mapper to set {self.upvotes(-1)} for.", upvotes=f"New number of {self.upvotes(-1)}.", reason=f"Justification.")
        async def setmapperupvotes(interaction: discord.Interaction, user: discord.Member, upvotes: int, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} set {target_user_mention} to {self.upvotes(upvotes)} (mapper) with reason: {reason}.",interaction.user.id)

                check_user(db,user.id)

                def set_upvotes_fun(previous):
                    return upvotes

                (previous_upvotes, new_upvotes) = await self.update_mapper_upvotes(db,user.id,set_upvotes_fun,cause_id=command_id)

                await self.send_response(interaction, f"Mapper upvotes for {target_user_mention} set from {self.upvotes(previous_upvotes)} to {self.upvotes(new_upvotes)}.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Set {self.upvotes(-1)} count of critic.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user=f"Critic to set {self.upvotes(-1)} for.", upvotes=f"New number of {self.upvotes(-1)}.", reason="Justification.")
        async def setcriticupvotes(interaction: discord.Interaction, user: discord.Member, upvotes: int, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} set {target_user_mention} to {self.upvotes(upvotes)} (critic) with reason: {reason}.",interaction.user.id)

                check_user(db,user.id)

                def set_upvotes_fun(previous):
                    return upvotes

                (previous_upvotes, new_upvotes) = await self.update_critic_upvotes(db,user.id,set_upvotes_fun,cause_id=command_id)

                await self.send_response(interaction, f"Critic upvotes for {target_user_mention} set from {self.upvotes(previous_upvotes)} to {self.upvotes(new_upvotes)}.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()   
            
        @self.tree.command(description=f"(Admin only) Set {self.penalties(-1)} count of user.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(user=f"User to set {self.penalties(-1)} for.", penalties=f"New number of {self.penalties(-1)}.", reason="Justification.")
        async def setpenalties(interaction: discord.Interaction, user: discord.Member, penalties: int, reason: str):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                target_user_mention = self.mention_user(user.id)
                command_id = await self.log_command(db,f"{user_mention} set {target_user_mention} to {self.penalties(penalties)} with reason: {reason}.",interaction.user.id)

                check_user(db,user.id)

                def set_penalties_fun(previous):
                    return penalties

                (previous_penalties, new_penalties) = await self.update_penalties(db,user.id,set_penalties_fun,cause_id=command_id)

                await self.send_response(interaction, f"Penalties for {target_user_mention} set from {self.penalties(previous_penalties)} to {self.penalties(new_penalties)}.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Check {self.stars(-1)} leaderboard.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(max_critics="Maximum number of critics to show.")
        async def starleaderboard(interaction: discord.Interaction, max_critics:int = 10, historic: bool = False):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                if historic:
                    message = f"{user_mention} checked the **historic** {self.stars(-1)} leaderboard (maximum of {max_critics} critics)."
                else:
                    message = f"{user_mention} checked the {self.stars(-1)} leaderboard (maximum of {max_critics} critics)."

                command_id = await self.log_command(db,message,interaction.user.id)
                
                cur = db.cursor()

                if historic:
                    query = """
                        SELECT
                            u.user_id,
                            u.stars,
                            u.historic_stars
                        FROM user u
                        ORDER BY u.historic_stars DESC
                        LIMIT :max_critics
                        """
                else:
                    query = """
                        SELECT
                            u.user_id,
                            u.stars,
                            u.historic_stars
                        FROM user u
                        ORDER BY u.stars DESC
                        LIMIT :max_critics
                        """
                
                data = {"max_critics":max_critics}
                res = cur.execute(query,data)
                critics = res.fetchall()                                
                                
                i = 0
                for critic in critics:
                    i += 1
                    (user_id, stars, historic_stars) = critic
                    critic_mention = self.mention_user(user_id)
                    await self.send_admin_channel(f"{i} - {critic_mention} - {self.stars(stars)} / {self.stars(historic_stars)} (historic)")
                
                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Check critic {self.upvotes(-1)} leaderboard.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(max_critics="Maximum number of critics to show.")
        async def criticupvoteleaderboard(interaction: discord.Interaction, max_critics:int = 10, historic: bool = False):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                if historic:
                    message = f"{user_mention} checked the **historic** critic {self.upvotes(-1)} leaderboard (maximum of {max_critics} critics)."
                else:
                    message = f"{user_mention} checked the critic {self.upvotes(-1)} leaderboard (maximum of {max_critics} critics)."

                command_id = await self.log_command(db,message,interaction.user.id)
                
                cur = db.cursor()

                if historic:
                    query = """
                        SELECT
                            u.user_id,
                            u.critic_upvotes,
                            u.historic_critic_upvotes
                        FROM user u
                        ORDER BY u.historic_critic_upvotes DESC
                        LIMIT :max_critics
                        """
                else:
                    query = """
                        SELECT
                            u.user_id,
                            u.critic_upvotes,
                            u.historic_critic_upvotes
                        FROM user u
                        ORDER BY u.critic_upvotes DESC
                        LIMIT :max_critics
                        """
                
                data = {"max_critics":max_critics}
                res = cur.execute(query,data)
                critics = res.fetchall()                                
                                
                i = 0
                for critic in critics:
                    i += 1
                    (user_id, critic_upvotes, historic_critic_upvotes) = critic
                    critic_mention = self.mention_user(user_id)
                    await self.send_admin_channel(f"{i} - {critic_mention} - {self.upvotes(critic_upvotes)} / {self.upvotes(historic_critic_upvotes)} (historic)")
                
                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Check mapper {self.upvotes(-1)} leaderboard.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(max_mappers="Maximum number of mappers to show.")
        async def mapperupvoteleaderboard(interaction: discord.Interaction, max_mappers:int = 10, historic: bool = False):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                if historic:
                    message = f"{user_mention} checked the **historic** mapper {self.upvotes(-1)} leaderboard (maximum of {max_mappers} mappers)."
                else:
                    message = f"{user_mention} checked the mapper {self.upvotes(-1)} leaderboard (maximum of {max_mappers} mappers)."

                command_id = await self.log_command(db,message,interaction.user.id)
                
                cur = db.cursor()

                if historic:
                    query = """
                        SELECT
                            u.user_id,
                            u.mapper_upvotes,
                            u.historic_mapper_upvotes
                        FROM user u
                        ORDER BY u.historic_mapper_upvotes DESC
                        LIMIT :max_mappers
                        """
                else:
                    query = """
                        SELECT
                            u.user_id,
                            u.mapper_upvotes,
                            u.historic_mapper_upvotes
                        FROM user u
                        ORDER BY u.mapper_upvotes DESC
                        LIMIT :max_mappers
                        """
                
                data = {"max_mappers":max_mappers}
                res = cur.execute(query,data)
                mappers = res.fetchall()                                
                                
                i = 0
                for mapper in mappers:
                    i += 1
                    (user_id, mapper_upvotes, historic_mapper_upvotes) = mapper
                    mapper_mention = self.mention_user(user_id)
                    await self.send_admin_channel(f"{i} - {mapper_mention} - {self.upvotes(mapper_upvotes)} / {self.upvotes(historic_mapper_upvotes)} (historic)")
                
                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Check critic completed requests leaderboard.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(max_critics="Maximum number of critics to show.")
        async def criticcompletionleaderboard(interaction: discord.Interaction, max_critics:int = 10):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                message = f"{user_mention} checked the critic completed requests leaderboard (maximum of {max_critics} critics)."

                command_id = await self.log_command(db,message,interaction.user.id)
                
                cur = db.cursor()

                query = """
                    SELECT
                        u.user_id,
                        u.completed_critic_requests
                    FROM user u
                    ORDER BY u.completed_critic_requests DESC
                    LIMIT :max_critics
                    """
                
                data = {"max_critics":max_critics}
                res = cur.execute(query,data)
                critics = res.fetchall()                                
                                
                i = 0
                for critic in critics:
                    i += 1
                    (user_id, critic_requests) = critic
                    critic_mention = self.mention_user(user_id)
                    await self.send_admin_channel(f"{i} - {critic_mention} - {critic_requests} completed critic requests")
                
                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close

        @self.tree.command(description=f"(Admin only) Check mapper completed requests leaderboard.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.describe(max_mappers="Maximum number of mappers to show.")
        async def mappercompletionleaderboard(interaction: discord.Interaction, max_mappers:int = 10):
            await self.defer(interaction)
            if not await self.check_admin_channel(interaction):                    
                return

            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                message = f"{user_mention} checked the mapper completed requests leaderboard (maximum of {max_mappers} critics)."

                command_id = await self.log_command(db,message,interaction.user.id)
                
                cur = db.cursor()

                query = """
                    SELECT
                        u.user_id,
                        u.completed_mapper_requests
                    FROM user u
                    ORDER BY u.completed_mapper_requests DESC
                    LIMIT :max_mappers
                    """
                
                data = {"max_mappers":max_mappers}
                res = cur.execute(query,data)
                mappers = res.fetchall()                                
                                
                i = 0
                for mapper in mappers:
                    i += 1
                    (user_id, mapper_requests) = mapper
                    mapper_mention = self.mention_user(user_id)
                    await self.send_admin_channel(f"{i} - {mapper_mention} - {mapper_requests} completed mapper requests")
                
                await self.send_response(interaction, "Command complete.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close()

        @self.tree.command(description=f"(Admin only) Reset {self.stars(-1)} and {self.upvotes(-1)} leaderboards.")
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)        
        async def resetleaderboards(interaction: discord.Interaction):
            await self.defer(interaction)
            
            db = self.db_connect()

            try:
                user_mention = self.mention_user(interaction.user.id)
                message = f"{user_mention} reset the {self.stars(-1)} and {self.upvotes(-1)} leaderboards."

                command_id = await self.log_command(db,message,interaction.user.id)
                
                cur = db.cursor()

                query = """
                    SELECT
                        u.user_id
                    FROM user u                    
                    """
                
                res = cur.execute(query)
                user_ids = [x[0] for x in res.fetchall()]

                def reset_fun(previous):
                    return 0

                for user_id in user_ids:
                    await self.update_stars(db,user_id,reset_fun,cause_id=command_id,update_historic=False)
                    await self.update_mapper_upvotes(db,user_id,reset_fun,cause_id=command_id,update_historic=False)
                    await self.update_critic_upvotes(db,user_id,reset_fun,cause_id=command_id,update_historic=False)
                
                await self.send_response(interaction, f"The {self.stars(-1)} and {self.upvotes(-1)} leaderboards have been reset.")
            except Exception as e:                
                await self.log_system(db, f"UNCAUGHT EXCEPTION! - {str(e)}")
            
            db.close       