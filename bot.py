from cheesyutils.discord_bots import DiscordBot


bot = DiscordBot(
    prefix=";",
    color="#843da4",
    members_intent=True,
    status="idle"
)

bot.load_extension("cogs.appeals")

bot.run("token.txt")
