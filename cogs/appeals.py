import datetime
import discord
import re
import urllib.parse
from discord.ext import commands
from cheesyutils.discord_bots import DiscordBot, Embed, Paginator, human_timedelta
from typing import List, Optional, Union
from enum import Enum
from io import StringIO


class _InvalidURL(commands.BadArgument):
    """Raised when a `_URLConverter` fails to convert a string into a url

    This inherits from `discord.ext.commands.BadArgument`
    """

    def __init__(self, argument: str, *args, **kwargs):
        self.argument = argument
        super().__init__(*args, **kwargs)


class _URLConverter(commands.Converter):
    """Converter to convert strings into URLS"""

    async def convert(self, ctx: commands.Context, argument: str):
        """Attempts to convert the given argument into a url

        Parameters
        ----------
        ctx : commands.Context
            The invokation context, usually fed from an executing command
        argument : str
            The argument to attempt to convert into a named cog
        
        Raises
        ------
        `InvalidURL` if the cog was not found
        """

        if not re.match(r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)", argument):
            raise _InvalidURL(argument)
        return argument


class ModlogChannel(Enum):
    invites = "invites_channel_id"
    joins = "joins_channel_id"


class ConfigChannel(Enum):
    invite = "invite_channel_id"
    system_joins = "system_channel_id"


class ConfigType(Enum):
    config = "config"
    modlog = "modlog_channels"


class Appeals(commands.Cog):
    """Contains commands and listeners for managing Ban Appeals"""

    def __init__(self, bot: DiscordBot):
        self.bot = bot

    @staticmethod
    def _is_stale_invite(invite: discord.Invite) -> bool:
        return invite.uses == 0 and invite.max_uses == 1 and (datetime.datetime.utcnow() - invite.created_at).days >= 7

    async def _fetch_channel_type(self, guild: discord.Guild, config_type: ConfigType, channel: Enum) -> Optional[discord.TextChannel]:
        row = await self.bot.database.query_first(
            sql=f"SELECT {channel.value} FROM {config_type.value} WHERE server_id = ?",
            parameters=(guild.id,)
        )

        if row:
            try:
                channel_id = int(row[channel.value])
            except ValueError:
                return None
            
            channel = await self.bot.retrieve_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                return channel
        
        return None

    async def _fetch_user_notes(self, guild: discord.Guild, user: discord.User) -> Optional[List[dict]]:
        """Retrieves a user's notes for a particular server

        In the event that a user does not have any notes, this returns `None`

        Parameters
        ----------
        guild : discord.Guild
            The guild to fetch the notes from.
        user : discord.User
            The user to fetch the notes for.

        Returns
        -------
        A list of dictionary entries for a user's notes if they have any, `None` otherwise
        """

        rows = await self.bot.database.query_all(
            "SELECT link, text FROM notes WHERE server_id = ? AND user_id = ? ORDER BY created_at DESC",
            parameters=(guild.id, user.id)
        )

        if rows:
            return rows
        return None

    async def _fetch_modlog_channel(self, guild: discord.Guild, channel: ModlogChannel) -> Optional[discord.TextChannel]:
        """Retrieves a particular modlog channel for a guild

        If a particular channel is not set, or if the channel returned is not a `discord.TextChannel`, this will return `None`

        Parameters
        ----------
        guild : discord.Guild
            The guild to retrieve the modlog channel for
        channel : ModlogChannel
            The modlog channel type to retrieve
        
        Returns
        -------
        The `discord.TextChannel` modlog channel if set, `None` otherwise
        """

        return await self._fetch_channel_type(guild, ConfigType.modlog, channel)


    async def _fetch_joins(self, guild: discord.Guild, user: Union[discord.Member, discord.User]) -> List[dict]:
        """Returns a list of all the join logs a particular user has within a particular guild

        Parameters
        ----------
        guild : discord.Guild
            The guild to fetch the join logs from
        user : Union(discord.Member, discord.User)
            The user to fetch the join logs for

        Returns
        -------
        A list of dictionaries, each dict representing one join log
        """

        return await self.bot.database.query_all(
            "SELECT server_id, user_id, joined_at, message_link FROM joins WHERE server_id = ? AND user_id = ? ORDER BY joined_at DESC",
            parameters=(guild.id, user.id)
        )

    def _get_time_string_since(self, start: datetime.datetime):
        """Returns a string expressing the ammount of time since a particular date time

        Parameters
        ----------
        start : datetime.datetime
            The datetime object to reference as the start
        
        Returns
        -------
        A string for the expressing the ammount of time since the date time specified
        """

        elapsed = datetime.datetime.utcnow() - start
        if elapsed.days > 0:
            return f"{elapsed.days} days ago"
        else:
            hours = round(elapsed.seconds / 3600, 2)
            if hours > 1:
                return f"{hours} hours ago"
            return f"{round(hours * 60, 2)} minutes ago"

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Ran when a member joins the server

        Parameters
        ----------
        member : discord.Member
            The member that joined the server
        """

        channel = await self._fetch_modlog_channel(member.guild, ModlogChannel.joins)
        if channel:
            # send join notification embed
            embed = Embed(
                title="New Ban Appeal",
                description=f"{member.mention} has joined the Ban Appeals Discord",
                author=member,
                timestamp=member.joined_at,
                color=self.bot.color
            ).set_footer(text="Joined At")

            # we may have to use this message as the join log message
            # if the server has an invalid system channel set
            message = await channel.send(member.id, embed=embed)
            message_link = message.jump_url

            # fetch system message link for the join log
            system_channel = await self.bot.database.query_first(
                "SELECT (system_channel_id) FROM config WHERE server_id = ?",
                parameters=(member.guild.id,)
            )
            channel_id = system_channel["system_channel_id"]

            system_channel = await self.bot.retrieve_channel(channel_id)
            if system_channel is not None and isinstance(channel, discord.TextChannel):
                # set message link to system message's link
                message = await system_channel.history(limit=1).flatten()
                message_link = message[0].jump_url
            else:
                # invalid channel set. use the bot's join log message instead
                message_link = message.jump_url

            # insert join log into joins table
            await self.bot.database.execute(
                "INSERT INTO joins (server_id, user_id, joined_at, message_link) VALUES (?, ?, ?, ?)",
                parameters=(member.guild.id, member.id, member.joined_at.timestamp(), message_link)
            )

            # check if the user has joined before
            joins = await self._fetch_joins(member.guild, member)
            if len(joins) > 1:
                # at least two total join logs found, including their most recent join
                embed = Embed(
                    title="Previous Join Log Found",
                    description=f"{member.mention} has previously joined the Ban Appeals Discord",
                    color=discord.Color.gold(),
                    author=member,
                ).set_footer(
                    text=f"User ID: {member.id}"
                ).add_field(
                    name="Join Count",
                    value=f"`{len(joins)}` - Run `.joins {member}` for full join logs"
                )

                await channel.send(member.id, embed=embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Ran when an invite is created

        This event automatically ignores non-guild invites (for private messages)

        Parameters
        ----------
        invite : discord.Invite
            The invite that was created
        """

        if invite.guild is None:
            return

        # fetch the invite guild's modlog channel for invite creation (if any)
        # there is a rare chance that the invite's guild attribute
        # is of type `discord.Object` instead of `discord.Guild`
        # we don't care about the type cause we just want the id
        channel = await self._fetch_modlog_channel(invite.guild, ModlogChannel.invites)
        if channel:
            embed = Embed(
                title="Invite Created",
                description=f"Invite for channel <#{invite.channel.id}> created by {invite.inviter.mention}",
                color=discord.Color.blurple(),
            ).set_footer(
                text=f"Inviter ID: {invite.inviter.id}"
            ).add_field(
                name="Temporary Membership?",
                value="Yes" if invite.temporary else "No"
            ).add_field(
                name="Expires?",
                value=f"Yes ({invite.max_age // 60} minutes)" if invite.max_age else "No"
            ).add_field(
                name="Max Uses",
                value=invite.max_uses if invite.max_uses else "Infinite"
            ).add_field(
                name="URL",
                value=str(invite),
                inline=False
            )

            await channel.send(invite.inviter.id, embed=embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Ran when an invite is deleted

        This event automatically ignores non-guild invites (for private messages)

        Parameters
        ----------
        invite : discord.Invite
            The invite that was created
        """

        if invite.guild is None:
            return

        # fetch the invite guild's modlog channel for invite deletion (if any)
        # there is a rare chance that the invite's guild attribute
        # is of type `discord.Object` instead of `discord.Guild`,
        # we don't care about the type cause we just want the id
        channel = await self._fetch_modlog_channel(invite.guild, ModlogChannel.invites)
        if channel:
            embed = Embed(
                title="Invite Deleted",
                description=f"Invite for channel <#{invite.channel.id}> deleted",
                color=discord.Color.gold(),
            ).add_field(
                name="URL",
                value=str(invite)
            )

            # sometimes the invite's inviter is `None`
            if invite.inviter:
                content = invite.inviter.id
            else:
                content = "Unknown Inviter"

            await channel.send(content, embed=embed)
            

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # TODO: This will eventually be the auto appeal thingymagig
        pass

    async def _fetch_stale_one_time_invites(self, guild: discord.Guild) -> List[discord.Invite]:
        """Fetches stale single-use invites for a particular guild

        A "stale" invite is defined as an invite that has not been used in over 24 hours

        The bot must have the `manage_channels` permission to be able to use this, otherwise `discord.Forbidden` will be raised.

        The list returned is sorted by creation date (oldest first)

        Parameters
        ----------
        guild : discord.Guild
            The guild to retrieve the invites for
        
        Raises
        ------
        `discord.Forbidden` if the bot did not have the required permissions to fetch invites
        `discord.HTTPException` if the bot failed to fetch invites

        Returns
        -------
        List[discord.Invite]
        """

        invites = await guild.invites()
        return sorted([invite for invite in invites if self._is_stale_invite(invite)], key=lambda i: i.created_at)
    
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, add_reactions=True, manage_messages=True, manage_channels=True)
    @commands.group(name="invites")
    async def invites_group(self, ctx: commands.Context):
        """
        Command group for current invite management
        If ran on it's own, this sends a list of the guild's invites
        """

        if not ctx.invoked_subcommand and not ctx.subcommand_passed:
            invites = await ctx.guild.invites()
            invites = sorted(invites, key=lambda i: i.created_at)

            await Paginator.from_sequence(
                invites,
                base_embed=Embed(
                    title="Active Invites",
                    description="{0.url} - {0.inviter.mention} - Used {0.uses}/{0.max_uses} times",
                    color=self.bot.color,
                    author=ctx.guild
                )
            ).paginate(ctx)
    
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, add_reactions=True, manage_messages=True, manage_channels=True)
    @invites_group.group(name="purge")
    async def invites_purge_group(self, ctx: commands.Context):
        """
        Command group for purging invites
        """

        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.invites_purge_group)

    async def _fetch_all_stale_single_use_invites(self, guild: discord.Guild) -> List[discord.Invite]:
        invites = await guild.invites()
        invites = sorted(invites, key=lambda i: i.created_at)
        ret = []
        for invite in invites:
            if self._is_stale_invite(invite):
                ret.append(invite)
        
        return ret

    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, add_reactions=True, manage_messages=True, manage_channels=True)
    @invites_purge_group.command(name="test")
    async def invites_purge_test_command(self, ctx: commands.Context):
        """
        Returns all stale, one-time use invites that would be purged. Does not actually purge any invites
        """

        invites = await self._fetch_all_stale_single_use_invites(ctx.guild)

        if invites:
            # TODO - I'd much rather have this display the invite creation date rather than the use count for each invite
            await Paginator.from_sequence(
                invites,
                base_embed=Embed(
                    title="Stale One-Time Invites to be Purged",
                    description="{0.url} - {0.inviter.mention} - Used {0.uses}/{0.max_uses} times",
                    color=self.bot.color,
                    author=ctx.guild
                )
            ).paginate(ctx)
        else:
            await self.bot.send_fail_embed(ctx, "No stale one-time invites found")

    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, add_reactions=True, manage_messages=True, manage_channels=True)
    @invites_purge_group.command(name="purge")
    async def invites_purge_purge_command(self, ctx: commands.Context):
        """
        Purges all stale, one-time use invites that are a day or older
        """

        invites = await self._fetch_all_stale_single_use_invites(ctx.guild)
        revoked = 0
        for invite in invites:
            try:
                await invite.delete()
                revoked += 1
            except discord.HTTPException:
                pass
                
        await self.bot.send_success_embed(ctx, f"Revoked {revoked} stale invites")

    async def _create_one_time_invite_for_invite_channel(self, guild: discord.Guild, requester: discord.User) -> discord.Invite:
        """Generates a new one-time use invite link for the guild's specific invite channel (if any)

        If the guild does not have a specified invite channel this will raise `ValueError`

        Parameters
        ----------
        guild : discord.Guild
            The guild for which to retrieve the invite for
        requester : discord.User
            The user that is requesting the invite
        
        Raises
        ------
        `commands.CommandError` if the guild has a missing or invalid invite channel set

        Returns
        -------
        A `discord.Invite` for the specified guild's invite channel
        """

        channel = await self._fetch_channel_type(guild, ConfigType.config, ConfigChannel.invite)
        if channel:
            return await channel.create_invite(max_uses=1, reason=f"Requested by {requester}")
        
        raise ValueError(f"Invalid or missing invite channel for guild {guild.id}")
    
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True, create_instant_invite=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_channels=True, create_instant_invite=True)
    @commands.command(name="invite")
    async def invite_command(self, ctx: commands.Context, mode: Optional[str]):
        """
        Creates a new one time use, never expiring invite for the server

        `mode` is an optional parameter. When this is set to "new", this will force the bot to generate a new invite instead of using a stale one.
        Note that this should not be used regularly to prevent old and stale invites from stacking up
        """

        if mode and mode.strip().lower() == "new":
            using_stale_invite = False
            invite = await self._create_one_time_invite_for_invite_channel(ctx.guild, ctx.author)
        else:
            # fetch stale invites if able
            stale_invites = await self._fetch_stale_one_time_invites(ctx.guild)

            # check if there is at least one stale invite that can be used
            if len(stale_invites) != 0:
                # there is at least one stale invite that can be used
                # just select the oldest stale invite
                invite = stale_invites[0]
                using_stale_invite = True
            else:
                # no stale invites available, create a new one
                using_stale_invite = False
                invite = await self._create_one_time_invite_for_invite_channel(ctx.guild, ctx.author)

        
        # determine title
        title = "Ban Appeals Invite"
        title += " (using \"stale\" invite. Use `.invite new` to bypass using stale invites)" if using_stale_invite else ""

        embed = Embed(
            title=title,
            description="This invite link will expire after one use",
            author=ctx.guild,
            color=self.bot.color,
        ).set_footer(
            icon_url=ctx.author.avatar_url,
            text=f"Requested by {ctx.author} ({ctx.author.id})"
        )

        if using_stale_invite:
            embed.add_field(
                name="NOTE",
                value="This invite was created from the oldest \"stale\" invite (aka a one-time-use invite that has not been used in over 24 hours)"
            )
        
        await ctx.send(invite, embed=embed)

    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True, send_messages=True, embed_links=True, attach_files=True)
    @commands.command(name="unbanall", aliases=["massunban"])
    async def unbanall_command(self, ctx: commands.Context, users: commands.Greedy[discord.User], *, reason: Optional[str] = "No reason given"):
        """
        Unbans a list of users
        """
        
        if users:
            async with ctx.typing():
                unbanned = []
                for user in users:
                    await ctx.guild.unban(user, reason=reason)
                    unbanned.append(user)

                await ctx.send(
                    embed=Embed(description=f":white_check_mark: Unbanned {len(unbanned)} users", color=self.bot.color),
                    file=discord.File(
                        StringIO("\n".join([f"{user} - {user.id}" for user in unbanned])),
                        filename="Unbanned Users.txt"
                    )
                )
        else:
            await ctx.send_help(self.unbanall_command)

    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True, send_messages=True, embed_links=True, attach_files=True)
    @commands.command(name="banall", aliases=["massban"])
    async def banall_command(self, ctx: commands.Context, users: commands.Greedy[discord.User], *, reason: Optional[str] = "No reason given"):
        """
        Bans a list of users. Does not delete messages.
        """

        if users:
            async with ctx.typing():
                banned = []
                for user in users:
                    await ctx.guild.ban(user, delete_message_days=0, reason=reason)
                    banned.append(user)

                await ctx.send(
                    embed=Embed(description=f":white_check_mark: Banned {len(banned)} users", color=self.bot.color),
                    file=discord.File(
                        StringIO("\n".join([f"{user} - {user.id}" for user in banned])),
                        filename="Banned Users.txt"
                    )
                )
        else:
            await ctx.send_help(self.banall_command)

    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True, send_messages=True, embed_links=True, attach_files=True)
    @commands.command(name="kickall", aliases=["masskick"])
    async def kickall_command(self, ctx: commands.Context, members: commands.Greedy[discord.Member], *, reason: Optional[str] = "No reason given"):
        """
        Kicks a list of members.
        """

        if members:
            async with ctx.typing():
                kicked = []
                for member in members:
                    await member.kick(reason=reason)
                    kicked.append(member)

                await ctx.send(
                    embed=Embed(description=f":white_check_mark: Kicked {len(kicked)} users", color=self.bot.color),
                    file=discord.File(
                        StringIO("\n".join([f"{user} - {user.id}" for user in kicked])),
                        filename="Kicked Users.txt"
                    )
                )
        else:
            await ctx.send_help(self.kickall_command)

    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_messages=True, add_reactions=True)
    @commands.group(name="notes")
    async def notes_group(self, ctx: commands.Context):
        """
        Notes command group

        A Discord user id may be supplied in order to fetch notes for a particular user. Doing this is equivalent to running `notes get <user_id>`
        """

        if ctx.invoked_subcommand is None:
            await ctx.send_help(self.notes_group)

    @notes_group.error
    async def on_notes_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MemberNotFound):
            await self.bot.send_fail_embed(ctx, f"No member {error.argument!r} found")

    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_messages=True, add_reactions=True)
    @notes_group.command(name="get", aliases=["for", "retrieve", "fetch"])
    async def notes_get_command(self, ctx: commands.Context, member: discord.Member):
        """
        Retrieves the notes for a particular user, if any
        """

        notes = await self._fetch_user_notes(ctx.guild, member)
        if notes:
            note_texts = [f"[{urllib.parse.unquote_plus(note['text'])}]({note['link']})" for note in notes]
            await Paginator.from_sequence(
                note_texts,
                base_embed=Embed(
                    title="Appeal Notes",
                    description="• {}",
                    color=self.bot.color,
                    author=member
                )
            ).paginate(ctx)
        else:
            await self.bot.send_fail_embed(ctx, f"{member} has no appeal notes")

    @notes_get_command.error
    async def on_notes_get_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MemberNotFound):
            await self.bot.send_fail_embed(ctx, f"No member \"{error.argument}\" found")
    
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_messages=True, add_reactions=True)
    @notes_group.command(name="rename")
    async def notes_rename_command(self, ctx: commands.Context, member: discord.Member, note_id: int, *, new_name: str):
        """
        Changes the name of a particular note with a given id
        """
        
        notes = await self._fetch_user_notes(ctx.guild, member)
        if notes:
            try:
                note = notes[note_id+1]
                await self.bot.database.execute(
                    "UPDATE notes SET text = ? WHERE server_id = ? AND user_id = ? AND text = ?",
                    parameters=(new_name, ctx.guild.id, member.id, urllib.parse.quote_plus(note["text"]))
                )

                await self.bot.send_success_embed(ctx, "Successfully renamed note")
            except IndexError:
                await self.bot.send_fail_embed(ctx, "Invalid note ID")

        else:
            await self.bot.send_fail_embed(ctx, f"{member} has no appeal notes")


    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_messages=True, add_reactions=True)
    @notes_group.command(name="add", aliases=["set", "put", "push"])
    async def notes_add_command(self, ctx: commands.Context, member: discord.Member, url: _URLConverter, *, text: Optional[str] = None):
        """
        Creates a new note for a user

        `url` must be a valid url. This can be a message link, image link, or a link to a particular website

        If `text` is not supplied, the text will default to "link n", where `n` is the latest note ID
        """

        # if no text is supplied, set note text to "link n"
        if text is None:
            notes = await self.bot.database.query_all(
                "SELECT user_id FROM notes WHERE server_id = ? AND user_id = ?",
                parameters=(ctx.guild.id, member.id)
            )

            text = f"Link {len(notes) + 1}"

        # insert new note
        await self.bot.database.execute(
            "INSERT INTO notes (server_id, user_id, moderator_id, link, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            parameters=(ctx.guild.id, member.id, ctx.author.id, url, urllib.parse.quote_plus(text), datetime.datetime.utcnow().timestamp())
        )

        # send confirmation embed
        embed = Embed(
            title="Appeal Note Created",
            description=f"[{text}]({url})",
            color=self.bot.color,
            author=member
        )

        await ctx.send(member.id, embed=embed)

    @notes_add_command.error
    async def on_notes_add_command_error(self, ctx: commands.Context, error):
        if isinstance(error, _InvalidURL):
            await self.bot.send_fail_embed(ctx, f"Invalid URL: {error.argument!r}")

    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_messages=True, add_reactions=True)
    @commands.command(name="joins", aliases=["fetchjoins", "getjoins", "joinsfor"])
    async def joins_command(self, ctx: commands.Context, user: Union[discord.Member, discord.User]):
        """
        Returns a list of all the times that a particular user has joined the server, if any
        """

        joins = await self._fetch_joins(ctx.guild, user)
        joins = [f"[{human_timedelta(datetime.datetime.fromtimestamp(join['joined_at']))}]({join['message_link']})" for join in joins]
        if joins:
            await Paginator.from_sequence(
                joins,
                base_embed=Embed(
                    title=f"Found {len(joins)} Join Logs",
                    description="{}",
                    color=self.bot.color,
                    author=user
                ).set_footer(
                    text="{}/{} Total Join Logs"
                )
            ).paginate(ctx)
        else:
            await self.bot.send_fail_embed(ctx, f"No join logs for {user}")

    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, manage_messages=True, add_reactions=True)
    @commands.command(name="appeals")
    async def appeals_command(self, ctx: commands.Context, appeal_id: Optional[int] = None):
        """
        Returns the list of current users with appeal roles

        If an integer is supplied afterwords, retrieves information about an appeal with a particular ID
        """

        # fetch the appeal roles for the server
        appeal_roles = await self.bot.database.query_all("SELECT role_id FROM appeals_roles WHERE server_id = ?", parameters=(ctx.guild.id,))
        appeal_roles = [role["role_id"] for role in appeal_roles]

        if appeal_roles:
            # fetch a list of all users with at least one of the appeal roles
            original = []
            for role_id in appeal_roles:
                role = ctx.guild.get_role(role_id)
                if role:
                    original += [user.id for user in role.members]
            
            # remove duplicates
            user_ids = []
            for user_id in original:
                if user_id not in user_ids:
                    user_ids.append(user_id)
            
            # create a list of members/join timestamps from those member ids
            # the resulting list is sorted by oldest "joined at" date
            members = []
            for user_id in user_ids:
                member = await self.bot.retrieve_member(ctx.guild, user_id)
                members.append([member, self._get_time_string_since(member.joined_at)])
            members = sorted(members, key=lambda m: m[0].joined_at)
        else:
            return await ctx.send("No appeal roles set")

        # either return information about a specific appeal
        # or return a list of all appeals
        # this is, of course, assuming that any appeals exist at all
        if len(members) != 0:
            if appeal_id is None:
                return await Paginator.from_sequence(
                    members,
                    base_embed=Embed(
                        title="Pending Appeals",
                        description="• `{0[0]}` - Joined {0[1]}",
                        color=self.bot.color,
                        author=ctx.guild
                    ).set_footer(text="Page {}/{}")
                ).paginate(ctx)
            else:
                # get info for specific appeal
                # the appeal_id might be out of range, hence the try block
                try:
                    if appeal_id > 0:
                        appeal = members[appeal_id - 1][0]

                        embed = Embed(
                            title="Appeal Info",
                            color=appeal.top_role.color,
                            author=ctx.guild,
                            footer=appeal
                        ).add_field(
                            name="User",
                            value=appeal
                        ).add_field(
                            name="Top Role",
                            value=appeal.top_role.mention
                        ).add_field(
                            name="Last Joined",
                            value=human_timedelta(member.joined_at)
                        )

                        # fetch note count
                        note_count = await self.bot.database.query_all("SELECT user_id, created_at FROM notes WHERE server_id = ? and user_id = ?", parameters=(ctx.guild.id, appeal.id), as_dict=False)
                        if note_count:
                            embed.add_field(
                                name="Note Count",
                                value=len(note_count)
                            )

                        return await ctx.send(appeal.id, embed=embed)
                    else:
                        raise IndexError
                except IndexError:
                    return await self.bot.send_warn_embed(ctx, f"That Appeal ID is out of range, try a number between `1` and `{len(members)}` instead")
        else:
            # no appeals found
            embed = Embed(
                title="No Appeals Found",
                description="There are no appeals! :broom::sparkles:",
                color=discord.Color.green(),
                author=ctx.guild
            )

            await ctx.send(embed=embed)


def setup(bot: DiscordBot):
    bot.add_cog(Appeals(bot))
