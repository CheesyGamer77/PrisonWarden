import discord
from discord.ext import commands
from cheesyutils.discord_bots import DiscordBot


class Miscellaneous(commands.Cog):
    """
    Miscellaneous commands
    """

    def __init__(self, bot: DiscordBot):
        self.bot = bot
    
    @commands.command(name="pineapple")
    async def pineapple_command(self, ctx: commands.Context):
        """
        :pineapple:
        """

        await ctx.send(":pineapple:")
    
    @commands.command(name="ping")
    async def ping_command(self, ctx: commands.Context):
        """
        :ping_pong: Pings the bot's websocket
        """

        await ctx.send(f"Pong! {round(self.bot.latency * 1000, 2)}ms")


def setup(bot: DiscordBot):
    bot.add_cog(Miscellaneous(bot))
