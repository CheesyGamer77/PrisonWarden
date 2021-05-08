FROM python:3

WORKDIR /usr/src/bot

# install required dependencies
RUN pip3 install -U cheesyutils
RUN pip3 install -U cheesyutils
RUN pip3 install -r requirements.txt

# start bot
CMD ["python3", "bot.py"]