import logging
import time
import discord
import re
import json
import aiohttp
import os
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

        with open("symbols.json") as file:
            self.symbol_data = json.load(file)
            file.close()

        with open("config.json") as file:
            config = json.load(file)
            self.ignored_currencies = config["ignored_currencies"]
            self.selected_currencies = config["selected_currencies"]
            file.close()

    async def handle_message(self, msg: str):
        currency_mentions = await self.scan_for_currency_mentions(msg)
        if len(currency_mentions) > 0:
            print("Got currency mentions: " + str(currency_mentions))

        replies_to_send = []
        for currency_mention in currency_mentions:
            reply = await self.build_currency_reply(currency_mention)
            if reply is not None:
                replies_to_send.append(reply)

        if len(replies_to_send) != 0:
            reply = "\n".join(replies_to_send)
            return reply
        else:
            return None

    async def scan_for_currency_mentions(self, msg: str):
        result = []

        # £12.34 $12.34 €12.34
        symbol_prefix_matches = list(re.finditer(r'([£€$₹])\s?(\d+(?:\.\d{1,2})?)', msg))
        for match in symbol_prefix_matches:
            code = self.currency_symbol_to_code(match[1])
            amount = str(float(match[2]))
            result.append(" ".join([code, amount]))

        # 12.34$ 12.34€
        symbol_suffix_matches = list(re.finditer(r'(\d+(?:\.\d{1,2})?)\s?([€$₹])', msg))
        for match in symbol_suffix_matches:
            code = self.currency_symbol_to_code(match[2])
            amount = str(float(match[1]))
            result.append(" ".join([code, amount]))

        # GBP 12.34
        code_prefix_matches = list(re.finditer(r'(?<!\w)([a-zA-Z]{3})\s?(\d+(?:\.\d{1,2})?)', msg))
        for match in code_prefix_matches:
            code = match[1].upper()
            amount = str(float(match[2]))
            result.append(" ".join([code, amount]))

        # 12.34 GBP
        code_suffix_matches = list(re.finditer(r'(\d+(?:\.\d{1,2})?)\s?([a-zA-Z]{3})(?!\w)', msg))
        for match in code_suffix_matches:
            code = match[2].upper()
            amount = str(float(match[1]))
            result.append(" ".join([code, amount]))

        # Strip out duplicates
        result = list(dict.fromkeys(result))

        # Filter out ignored currencies and unknown
        known_currencies = await self.currency_converter.known_currencies()
        acceptable_currencies = set(known_currencies) - set(self.ignored_currencies)
        result = list(filter(lambda x: x.split(" ")[0] in acceptable_currencies, result))

        # Return the array of strings, each in the format of "GBP 12.34"
        return result

    def currency_symbol_to_code(self, symbol):
        for row in self.symbol_data:
            if row['symbol'] == symbol:
                return row['currency']
        return symbol

    async def build_currency_reply(self, currency_mention):
        print("Building currency reply for input {0}".format(currency_mention))
        split = currency_mention.split(" ")
        from_currency = split[0]
        from_amount = float(split[1])

        target_results = []
        for target_currency in self.selected_currencies:
            if target_currency != from_currency:
                target_amount = await self.currency_converter.convert(from_amount, from_currency, target_currency)
                target_results.append("{0:.2f} {1}".format(target_amount, target_currency))

        if len(target_results) == 0:
            return None

        target_results_str = ", or ".join(target_results)
        reply = "{0:.2f} {1} is worth {2}.".format(from_amount, from_currency, target_results_str)
        return reply


class MoneyManClient(discord.Client):

    def __init__(self, **options):
        super().__init__(**options)
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
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        reply = await self.cmh.handle_message(message.content)
        if reply is not None:
            await message.reply(reply, mention_author=False)


if __name__ == "__main__":
    client = MoneyManClient()
    client.run(os.environ['DISCORD_TOKEN'])