FROM python:3

WORKDIR /usr/src/bot

# install required dependencies
RUN pip3 install python-dateutil
RUN pip3 install cheesyutils
RUN pip3 install aiohttp
RUN pip3 install discord.py
RUN pip3 install aiosqlite


# start bot
CMD ["python3", "bot.py"]
