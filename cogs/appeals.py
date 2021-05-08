import datetime
import discord
import re
import urllib.parse
from discord.ext import commands
from cheesyutils.discord_bots import DiscordBot
from cheesyutils.discord_bots.utils import paginate, get_base_embed
from typing import List, Optional


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


class Appeals(commands.Cog):
    """Contains commands and listeners for managing Ban Appeals"""

    def __init__(self, bot: DiscordBot):
        self.bot = bot

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
        guild_id = invite.guild.id
        config = await self.bot.database.query_first("SELECT (invite_creates_channel_id) FROM modlog_channels WHERE server_id = ?", parameters=(guild_id,))
        if config:
            # if there is a modlog channel defined, post the log
            channel_id = config["invite_creates_channel_id"]
            channel = await self.bot.retrieve_channel(channel_id)
            if channel is not None:
                embed = get_base_embed(
                    title="Invite Created",
                    description=f"Invite for channel <#{invite.channel.id}> created by {invite.inviter.mention}",
                    color=discord.Color.blurple(),
                    footer_text=f"Inviter ID: {invite.inviter.id}"
                )

                embed.add_field(
                    name="Temporary Membership?",
                    value="Yes" if invite.temporary else "No"
                )

                embed.add_field(
                    name="Expires?",
                    value=f"Yes ({invite.max_age // 60} minutes)" if invite.max_age else "No"
                )

                embed.add_field(
                    name="Max Uses",
                    value=invite.max_uses if invite.max_uses else "Infinite"
                )

                embed.add_field(
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
        guild_id = invite.guild.id
        config = await self.bot.database.query_first("SELECT (invite_deletes_channel_id) FROM modlog_channels WHERE server_id = ?", parameters=(guild_id,))
        if config:
            # if there is a modlog channel defined, post the log
            channel_id = config["invite_deletes_channel_id"]
            channel = await self.bot.retrieve_channel(channel_id)
            if channel is not None:
                embed = get_base_embed(
                    title="Invite Deleted",
                    description=f"Invite for channel <#{invite.channel.id}> deleted",
                    color=discord.Color.gold(),
                    footer_text=f"Inviter ID: {invite.inviter.id}"
                )

                embed.add_field(
                    name="Temporary Membership?",
                    value="Yes" if invite.temporary else "No"
                )

                embed.add_field(
                    name="Expires?",
                    value=f"Yes ({invite.max_age // 60} minutes)" if invite.max_age else "No"
                )

                embed.add_field(
                    name="Max Uses",
                    value=invite.max_uses if invite.max_uses else "Infinite"
                )

                embed.add_field(
                    name="URL",
                    value=str(invite),
                    inline=False
                )

                await channel.send(invite.inviter.id, embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
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

        def is_stale(invite: discord.Invite):
            return invite.uses == 0 and invite.max_uses == 1 and (datetime.datetime.utcnow() - invite.created_at).days >= 1

        invites = await guild.invites()
        return sorted([invite for invite in invites if is_stale(invite)], key=lambda i: i.created_at)
    
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, add_reactions=True, manage_messages=True, manage_channels=True)
    @commands.command(name="invites")
    async def invites_command(self, ctx: commands.Context):
        """
        Sends a list of the guild's invites
        """

        invites = await ctx.guild.invites()
        invites = sorted(invites, key=lambda i: i.created_at)

        await paginate(
            ctx,
            embed_title="Active Invites",
            embed_color=self.bot.color,
            line="{0.url} - {0.inviter.mention} - Used {0.uses}/{0.max_uses} times",
            sequence=invites
        )
    
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

        config = await self.bot.database.query_first(f"SELECT (invite_channel_id) FROM config WHERE server_id = {guild.id}")
        if config:
            channel_id = config["invite_channel_id"]
            channel = await self.bot.retrieve_channel(channel_id)
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

        if mode is not None and mode.strip().lower() == "new":
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
        title += " (using \"stale\" invite)" if using_stale_invite else ""

        embed = get_base_embed(
            title=title,
            description="This invite link will expire after one use",
            author=ctx.guild,
            color=self.bot.color,
            footer_icon=ctx.author,
            footer_text=f"Requested by {ctx.author} ({ctx.author.id})"
        )

        if using_stale_invite:
            embed.add_field(
                name="NOTE",
                value="This invite was created from the oldest \"stale\" invite (aka a one-time-use invite that has not been used in over 24 hours)"
            )
        
        await ctx.send(invite, embed=embed)

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
            if ctx.subcommand_passed is not None:
                member = await commands.MemberConverter().convert(ctx.subcommand_passed)
                await self.notes_get_command(ctx, member)

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

        notes = await self.bot.database.query_all("SELECT link, text FROM notes WHERE server_id = ? and user_id = ?", parameters=(ctx.guild.id, member.id))
        if notes:
            note_texts = [f"[{urllib.parse.unquote_plus(note['text'])}]({note['link']})" for note in notes]

            await paginate(
                ctx,
                embed_title="Ban Appeal Notes",
                embed_color=self.bot.color,
                sequence=note_texts,
                line="{0}",
                count_format="{0}) ",
                author_name=str(member),
                author_icon_url=member.avatar_url
            )
        else:
            await self.bot.send_fail_embed(ctx, f"{member} has no appeal notes")

    @notes_get_command.error
    async def on_notes_get_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MemberNotFound):
            await self.bot.send_fail_embed(ctx, f"No member \"{error.argument}\" found")

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
        embed = get_base_embed(
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
            await ctx.send("No appeal roles set")

        # either return information about a specific appeal
        # or return a list of all appeals
        # this is, of course, assuming that any appeals exist at all
        if len(members) != 0:
            if appeal_id is None:
                # paginate the member list
                return await paginate(
                    ctx,
                    embed_title="Pending Appeals",
                    embed_color=self.bot.color,
                    sequence=members,
                    line="`{0[0]}` - Joined {0[1]}",
                    sequence_type_name="members",
                    author_name=ctx.guild.name,
                    author_icon_url=ctx.guild.icon_url,
                    count_format="{0}) "
                )
            else:
                # get info for specific appeal
                # the appeal_id might be out of range, hence the try block
                try:
                    if appeal_id > 0:
                        appeal = members[appeal_id - 1][0]

                        embed = get_base_embed(
                            title="Appeal Info",
                            color=appeal.top_role.color,
                            author=ctx.guild,
                            footer=appeal
                        )

                        embed.add_field(
                            name="User",
                            value=appeal
                        )

                        embed.add_field(
                            name="Top Role",
                            value=appeal.top_role.mention
                        )

                        embed.add_field(
                            name="Joined",
                            value=self._get_time_string_since(appeal.joined_at)
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
            embed = get_base_embed(
                title="No Appeals Found",
                description="There are no appeals! :broom::sparkles:",
                color=discord.Color.green(),
                author=ctx.guild
            )

            await ctx.send(embed=embed)


def setup(bot: DiscordBot):
    bot.add_cog(Appeals(bot))
