require('dotenv').config()
let config = require("./config.json");

const util = require('util');

const money = require("money");
const oxr = require("open-exchange-rates");
oxr.set({app_id: process.env.OXR_APP_ID});
const oxrLatestAsync = util.promisify(oxr.latest);
let ratesLastUpdated = 0;

async function updateRates() {
    if ((Date.now() - ratesLastUpdated) > config["currencyRateTTL"]) {
        console.log("Updating exchange rates...");
        await oxrLatestAsync().then(function () {
            money.base = oxr.base;
            money.rates = oxr.rates;
            ratesLastUpdated = Date.now();
        });
    } else {
        console.log("Skipping update of exchange rates.");
    }
}

updateRates();


// DISCORD INIT //
const Discord = require("discord.js");
const client = new Discord.Client();
client.on("ready", async () => {
    console.log(`MoneyMan has started, with ${client.users.cache.size} users, in ${client.channels.cache.size} channels of ${client.guilds.cache.size} servers.`);

    const link = await client.generateInvite({
        "permissions": [
            "VIEW_CHANNEL",
            "CHANGE_NICKNAME",
            "SEND_MESSAGES",
            "MANAGE_MESSAGES",
            "EMBED_LINKS",
            "ATTACH_FILES",
            "READ_MESSAGE_HISTORY",
            "ADD_REACTIONS",
            "USE_EXTERNAL_EMOJIS"
        ]
    })
    console.log(link)

    //client.user.setActivity('Chemistry HQ', {type: 'WATCHING'});
    await client.user.setActivity();
});
client.on("guildCreate", guild => {
    console.log(`Joined server: ${guild.name} (id: ${guild.id}).`);
});
client.on("guildDelete", guild => {
    console.log(`Removed from server: ${guild.name} (id: ${guild.id})`);
});
client.login(process.env.DISCORD_TOKEN);

// COMMANDS //
const commands = {
    "forceRateUpdate": async function (client, message, args) {
        ratesLastUpdated = 0;
        await updateRates();
        message.channel.send("Rates updated from OXR.");
    }
}
client.on("message", async message => {  // This event will run on every single message received, from any channel or DM.
    // Ignore messages from bots (including self)
    if (message.author.bot) {
        return;
    }

    // Ignore messages that don't start with our prefix
    if (message.content.indexOf(config["commandPrefix"]) !== 0) {
        return;
    }

    // Split up the command/args
    const args = message.content.slice(config["commandPrefix"].length).trim().split(/ +/g);
    const command = args.shift().toLowerCase();

    if (commands.hasOwnProperty(command)) {
        var commandFunction = commands[command];
        return await commandFunction(client, message, args);
    } else {
        // unrecognized command
    }
});

// INLINE CURRENCY CONVERSION //
client.on("message", async message => {
    // Ignore messages from bots (including self)
    if (message.author.bot) {
        return;
    }

    const currencyMentions = scanForCurrencyMentions(message.content);
    if (currencyMentions > 0) {
        console.log("Got currency mentions: ", currencyMentions);
        await updateRates();
    }

    let repliesToSend = []

    for (const currencyMention of currencyMentions) {
        const split = currencyMention.split(" ");
        const fromCurrency = split[0];
        if (Object.keys(money.rates).includes(fromCurrency)) {
            repliesToSend.push(buildCurrencyReply(currencyMention));
        }
    }

    if (repliesToSend.length !== 0) {
        const reply = repliesToSend.join("\n")
        await message.channel.send(reply);
    }
});

function buildCurrencyReply(currencyMention) {
    console.log(`Building currency reply for input '${currencyMention}'`);
    const split = currencyMention.split(" ");
    const fromCurrency = split[0];
    const fromAmount = Number.parseFloat(split[1]);

    let targetResults = [];
    let targetCurrency;
    for (targetCurrency of config["selectedCurrencies"]) {
        if (targetCurrency !== fromCurrency) {
            const targetAmount = money.convert(fromAmount, {from: fromCurrency, to: targetCurrency});
            targetResults.push(`${targetAmount.toFixed(2)} ${targetCurrency}`);
        }
    }
    const targetResultString = targetResults.join(", or ");
    const reply = `${fromAmount.toFixed(2)} ${fromCurrency} is worth ${targetResultString}.`;
    return reply;
}

function scanForCurrencyMentions(msg) {
    let amount;
    let code;
    let match;
    let result = [];

    // £12.34 $12.34 €12.34
    const symbolPrefixMatches = msg.matchAll(/([£€$])\s?(\d+(?:\.\d{1,2})?)/g);
    for (match of symbolPrefixMatches) {
        code = currencySymbolToCode(match[1]);
        amount = Number.parseFloat(match[2]);
        result.push([code, amount].join(" "));
    }

    // 12.34$ 12.34€
    const symbolSuffixMatches = msg.matchAll(/(\d+(?:\.\d{1,2})?)\s?([€$])/g);
    for (match of symbolSuffixMatches) {
        code = currencySymbolToCode(match[2]);
        amount = Number.parseFloat(match[1]);
        result.push([code, amount].join(" "));
    }

    // GBP 12.34
    const codePrefixMatches = msg.matchAll(/(?<!\w)([a-zA-Z]{3})\s?(\d+(?:\.\d{1,2})?)/g);
    for (match of codePrefixMatches) {
        code = match[1].toUpperCase();
        amount = Number.parseFloat(match[2]);
        result.push([code, amount].join(" "));
    }

    // 12.34 GBP
    const codeSuffixMatches = msg.matchAll(/(\d+(?:\.\d{1,2})?)\s?([a-zA-Z]{3})(?!\w)/g);
    for (match of codeSuffixMatches) {
        code = match[2].toUpperCase();
        amount = Number.parseFloat(match[1]);
        result.push([code, amount].join(" "));
    }

    // Strip out duplicates
    result = [...new Set(result)];

    // Filter out ignored currencies
    result = result.filter(function (currencyStr) {
        return !config["ignoreCurrencies"].some(currency => currencyStr.startsWith(currency));
    });

    // return the array of strings, each in the format of "GBP 12.34"
    return result;
}

function currencySymbolToCode(symbol) {
    if (symbol === "£") {
        return "GBP";
    } else if (symbol === "€") {
        return "EUR";
    } else if (symbol === "$") {
        return "USD";
    }
}
