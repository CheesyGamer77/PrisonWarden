FROM python:3

WORKDIR /usr/src/bot

# install required dependencies
RUN pip3 install -U cheesyutils
RUN pip3 install -U cheesyutils
RUN pip3 install -U aiohttp
RUN pip3 install -U discord.py
RUN pip3 install -U aiosqlite

# start bot
CMD ["python3", "bot.py"]
