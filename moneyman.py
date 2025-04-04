import collections
import logging
import time
import discord
import re
import json
import aiohttp
import os
import datetime
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)


class CurrencyConverter:
    CACHE_FILE_NAME = "rates.json"

    def __init__(self):
        self.oxr_app_id = os.environ["OXR_APP_ID"]
        self.cached_rate_data = None
        try:
            with open(self.CACHE_FILE_NAME) as file:
                self.cached_rate_data = json.load(file)
                file.close()
        except FileNotFoundError:
            pass

    async def rate_data(self):
        if self.__is_data_valid(self.cached_rate_data):
            return self.cached_rate_data
        self.cached_rate_data = await self.__fetch_rate_data_from_oxr()
        try:
            with open(self.CACHE_FILE_NAME, 'w') as file:
                json.dump(self.cached_rate_data, file)
                file.close()
        except IOError:
            print("Failed to write rates cache file.")
        return await self.rate_data()

    def __is_data_valid(self, rate_data):
        if rate_data is None:
            return False
        ttl = 12 * 60 * 60
        age = time.time() - rate_data['timestamp']
        return age < ttl

    async def __fetch_rate_data_from_oxr(self):
        print("Fetching rate data from OXR")
        url = "https://openexchangerates.org/api/latest.json?app_id={}".format(self.oxr_app_id)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as r:
                if r.status == 200:
                    return await r.json()
                else:
                    print("Error fetching rate data. {0.status} {0}".format(r))
                    return None

    async def get_rate(self, from_currency, to_currency):
        rate_data = await self.rate_data()
        from_rate = rate_data["rates"][from_currency]
        to_rate = rate_data["rates"][to_currency]
        rate = to_rate / from_rate
        return rate

    async def convert(self, from_amount, from_currency, to_currency):
        rate = await self.get_rate(from_currency, to_currency)
        to_amount = from_amount * rate
        return to_amount

    async def known_currencies(self):
        rate_data = await self.rate_data()
        return list(rate_data['rates'].keys())


class CurrencyMessageHandler:

    def __init__(self):
        self.currency_converter = CurrencyConverter()
        self.ignored_currencies = []
        self.selected_currencies = []
        self.flags = {}

        with open("symbols.json") as file:
            self.symbol_data = json.load(file)
            file.close()

        with open("flags.json") as file:
            self.flags = json.load(file)
            file.close()

        with open("config.json") as file:
            config = json.load(file)
            self.ignored_currencies = config["ignored_currencies"]
            self.selected_currencies = config["selected_currencies"]
            file.close()

    async def handle_message(self, msg: str, response_reactions=[]):
        currency_mentions = await self.scan_for_currency_mentions(msg)
        if len(currency_mentions) > 0:
            print("Got currency mentions: " + str(currency_mentions))

        additional_target_currencies = self.get_currencies_from_response_reactions(response_reactions)
        target_currencies = self.selected_currencies + additional_target_currencies

        replies_to_send = []
        for currency_mention in currency_mentions:
            reply = await self.build_currency_reply(currency_mention, target_currencies)
            if reply is not None:
                replies_to_send.append(reply)

        if len(replies_to_send) != 0:
            reply = "\n".join(replies_to_send)
            return reply
        else:
            return None

    async def scan_for_currency_mentions(self, msg: str):
        expressions = [
            r'(?P<currency>[£€$₹])\s?(?P<quantity>\d+(?:\.\d{1,2})?)',  # £12.34 $12.34 €12.34
            r'(?P<quantity>\d+(?:\.\d{1,2})?)\s?(?P<currency>[€$₹])',  # 12.34$ 12.34€
            r'(?<!\w)(?P<currency>[a-zA-Z]{3})\s?(?P<quantity>\d+(?:\.\d{1,2})?)',  # GBP 12.34
            r'(?P<quantity>\d+(?:\.\d{1,2})?)\s?(?P<currency>[a-zA-Z]{3})(?!\w)'  # 12.34 GBP
        ]
        result_tuples = []
        for expression in expressions:
            for match in re.finditer(expression, msg):
                result_tuples.append(
                    (self.currency_symbol_to_code(match['currency']).upper(), float(match['quantity'])))

        # Strip out duplicates
        result_tuples = list(dict.fromkeys(result_tuples))

        # Filter out ignored currencies and unknown
        known_currencies = await self.currency_converter.known_currencies()
        acceptable_currencies = set(known_currencies) - set(self.ignored_currencies)
        result_tuples = list(filter(lambda x: x[0] in acceptable_currencies, result_tuples))

        # Return the array of tuples, each in the format of ("GBP", 12.34)
        return result_tuples

    def currency_symbol_to_code(self, symbol):
        for row in self.symbol_data:
            if row['symbol'] == symbol:
                return row['currency']
        return symbol

    async def build_currency_reply(self, currency_mention, target_currencies):
        print("Building currency reply for input {0}".format(currency_mention))
        from_currency = currency_mention[0]
        from_amount = currency_mention[1]

        target_results = []
        for target_currency in target_currencies:
            if target_currency != from_currency:
                target_amount = await self.currency_converter.convert(from_amount, from_currency, target_currency)
                target_results.append("{0:.2f} {1}".format(target_amount, target_currency))

        if len(target_results) == 0:
            return None

        target_results_str = ", or ".join(target_results)
        reply = "{0:.2f} {1} is worth {2}.".format(from_amount, from_currency, target_results_str)
        return reply

    def get_currencies_from_response_reactions(self, response_reactions):
        emojis = []
        for reaction in response_reactions:
            if (reaction.count > 0) and (not reaction.is_custom_emoji()):
                emojis.append(reaction.emoji)

        currencies = []
        for emoji in emojis:
            if emoji in self.flags:
                currencies.append(self.flags[emoji])
        return currencies


class MoneyManClient(discord.Client):

    def __init__(self, **options):
        super().__init__(**options)
        self.history = collections.deque(list(), 256)
        self.cmh = CurrencyMessageHandler()

    async def on_ready(self):
        print('Logged on as {0}'.format(self.user))
        print(await self.get_oauth_url())
        self.activity = None

    async def get_oauth_url(self):
        app_info = await self.application_info()
        perms = discord.Permissions(view_channel=True, change_nickname=True, send_messages=True, embed_links=True,
                                    attach_files=True, read_messages=True, read_message_history=True,
                                    add_reactions=True, use_external_emojis=True)
        url = discord.utils.oauth_url(client_id=app_info.id, scopes=('bot', 'applications.commands'), permissions=perms)
        return url

    async def on_guild_join(self, guild):
        print("Joined server: {0.name} (id: {0.id})".format(guild))

    async def on_guild_remove(self, guild):
        print("Removed from server: {0.name} (id: {0.id})".format(guild))

    async def on_message(self, message):
        print("Message received: {0})".format(message))
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        reply = await self.cmh.handle_message(message.content)
        if reply is not None:
            reply_msg = await message.reply(reply, mention_author=False)
            self.history.append(reply_msg)
        elif message.channel.type == discord.ChannelType.private:
            link = await self.get_oauth_url()
            reply = "You can add this bot to your own server using this link: {}".format(link)
            await message.channel.send(reply)

    async def find_history_message(self, source_message):
        for history_msg in self.history:
            if history_msg.reference.message_id == source_message.id:
                # Try to find the same message in self.cached_messages, because it may be more up-to-date.
                for cm in self.cached_messages:
                    if cm.id == history_msg.id:
                        return cm
                return history_msg

        for cached_msg in self.cached_messages:
            ref = cached_msg.reference
            if (cached_msg.author == self.user) and (ref is not None) and (ref.message_id == source_message.id):
                return cached_msg

        ch_messages = await source_message.channel.history(after=source_message, limit=25).flatten()
        for ch_msg in ch_messages:
            ref = ch_msg.reference
            if (ch_msg.author == self.user) and (ref is not None) and (ref.message_id == source_message.id):
                return ch_msg

        return None

    async def djr_find_msg(self, channel_id, message_id):
        for cm in self.cached_messages:
            if cm.id == message_id:
                return cm
        channel = self.get_channel(channel_id)
        try:
            print("Fetching message {}".format(message_id))
            return await channel.fetch_message(message_id)
        except discord.DiscordException:
            return None

    async def on_message_delete(self, message):
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        # If we replied to this deleted message recently, delete our reply.
        history_msg = await self.find_history_message(message)
        if history_msg is not None:
            await history_msg.delete()
            self.history.remove(history_msg)

    async def on_raw_message_edit(self, event):
        message = await self.djr_find_msg(event.channel_id, event.message_id)
        if message is None:
            return

        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        # The edit may mean we have to update our reply or create a new reply.
        history_msg = await self.find_history_message(message)
        if history_msg is not None:
            await self.update_existing_response(history_msg)
        else:
            if (datetime.datetime.now - message.created_at).seconds > (20 * 60):
                # Don't add new reply to old messages.
                return
            new_response = await self.cmh.handle_message(message.content)
            if new_response is not None:
                reply_msg = await message.reply(new_response, mention_author=False)
                self.history.append(reply_msg)

    async def on_raw_reaction_add(self, payload):
        message = await self.djr_find_msg(payload.channel_id, payload.message_id)
        await self.update_existing_response(message)

    async def on_raw_reaction_remove(self, payload):
        message = await self.djr_find_msg(payload.channel_id, payload.message_id)
        await self.update_existing_response(message)

    async def on_raw_reaction_clear(self, payload):
        message = await self.djr_find_msg(payload.channel_id, payload.message_id)
        await self.update_existing_response(message)

    async def on_raw_reaction_clear_emoji(self, payload):
        message = await self.djr_find_msg(payload.channel_id, payload.message_id)
        await self.update_existing_response(message)

    async def update_existing_response(self, existing_response_msg):
        if existing_response_msg is None:
            return
        if (existing_response_msg not in self.history) and (existing_response_msg.author != self.user):
            return

        source_msg_ref = existing_response_msg.reference
        if source_msg_ref is None:
            return
        source_msg = source_msg_ref.cached_message
        if source_msg is None:
            source_msg = await self.djr_find_msg(source_msg_ref.channel_id, source_msg_ref.message_id)
            if source_msg is None:
                return

        new_response = await self.cmh.handle_message(source_msg.content,
                                                     response_reactions=existing_response_msg.reactions)
        if new_response is None:
            await existing_response_msg.delete()
            self.history.remove(existing_response_msg)
        elif existing_response_msg.content != new_response:
            await existing_response_msg.edit(content=new_response, allowed_mentions=discord.AllowedMentions.none())


if __name__ == "__main__":
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    client = MoneyManClient(intents=intents)
    client.run(os.environ['DISCORD_TOKEN'])
