// config
var config = {
	"commandPrefix": "!",
	"currencyRateTTL": 12 * 60 * 60 * 1000,
	"selectedCurrencies": [
		"GBP",
		"EUR",
		"USD",
		"AUD",
		"CAD",
		"RON",
		"CHF"
	]
}


// // // // // //

require('dotenv').config()

const util = require('util');

const Discord = require("discord.js");
const client = new Discord.Client();

const money = require("money");
const oxr = require("open-exchange-rates");
oxr.set({app_id: process.env.OXR_APP_ID});
const oxrLatestAsync = util.promisify(oxr.latest);
var ratesLastUpdated = 0;
async function updateRates() {
	if ((Date.now() - ratesLastUpdated) > config["currencyRateTTL"]) {
		console.log("Updating exchange rates...");
		await oxrLatestAsync().then(function() {
			money.base = oxr.base;
			money.rates = oxr.rates;
			ratesLastUpdated = Date.now();
		});
	} else {
		console.log("Skipping update of exchange rates.");
	}
}
updateRates();

// // // // // // // //



// DISCORD INIT //
client.on("ready", () => {
	console.log(`ChemBot has started, with ${client.users.size} users, in ${client.channels.size} channels of ${client.guilds.size} servers.`);

	client.generateInvite(804781379)
  	.then(link => console.log(link))
  	.catch(console.error);

	client.user.setActivity('Chemistry', {type: 'WATCHING'});
});
client.on("guildCreate", guild => {
	console.log(`Joined server: ${guild.name} (id: ${guild.id}).`);
});
client.on("guildDelete", guild => {
	console.log(`Removed from server: ${guild.name} (id: ${guild.id})`);
});

// COMMANDS //
const commands = {
	"ping": async function(client, message, args) {
		// Calculates ping between sending a message and editing it, giving a nice round-trip latency.
		// The second ping is an average latency between the bot and the websocket server (one-way, not round-trip)
		const m = await message.channel.send("...");
		m.edit(`Pong! Latency is ${m.createdTimestamp - message.createdTimestamp}ms. API Latency is ${Math.round(client.ping)}ms`);
	},

	"forceRateUpdate": async function(client, message, args) {
		ratesLastUpdated = 0;
		await updateRates();
		message.channel.send("Rates updated from OXR.");
	},

	"convert": async function(client, message, args) {
		var inputAmount = args[0];
		var sourceCurrency = args[1];
		var destCurrency = args[2];
		var rates = swap.quoteSync({currency: {baseCurrency: sourceCurrency, quoteCurrency: destCurrency}, cache: true});
		console.log(rates);
	},

}
client.on("message", async message => {  // This event will run on every single message received, from any channel or DM.
	// Ignore messages from bots (including self)
	if(message.author.bot) return;

	// Ignore messages that don't start with our prefix
	if(message.content.indexOf(config["commandPrefix"]) !== 0) return;

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
	if(message.author.bot) return;

	var currencyMentions = scanForCurrencyMentions(message.content);
	if (currencyMentions > 0) {
		console.log("Got currency mentions: ", currencyMentions);
		updateRates();
	}
	for (currencyMention of currencyMentions) {
		var split = currencyMention.split(" ");
		var fromCurrency = split[0];
		if (Object.keys(money.rates).includes(fromCurrency) {
			var reply = buildCurrencyReply(currencyMention);
			message.channel.send(reply);
		}
	}
});

function buildCurrencyReply(currencyMention) {
	console.log(`Building currency reply for input '${currencyMention}'`);
	var split = currencyMention.split(" ");
	var fromCurrency = split[0];
	var fromAmount = Number.parseFloat(split[1]);

	var targetResults = [];
	console.log("selected ", config["selectedCurrencies"]);
	for (targetCurrency of config["selectedCurrencies"]) {
		console.log(`target ${targetCurrency}`);
		var targetAmount = money.convert(fromAmount, {from: fromCurrency, to: targetCurrency});
		targetResults.push(`${targetAmount.toFixed(2)} ${targetCurrency}`);
	}
	targetResultString = targetResults.join(", or ");

	var reply = `${fromAmount.toFixed(2)} ${fromCurrency} is worth ${targetResultString}.`;
	return reply;
}

function scanForCurrencyMentions(msg) {
	result = [];

	// £12.34 $12.34 €12.34
	var symbolPrefixMatches = msg.matchAll(/([£€$])\s?(\d+(?:\.\d{1,2})?)/g);
	for (match of symbolPrefixMatches) {
		var code = currencySymbolToCode(match[1]);
		var amount = Number.parseFloat(match[2]);
		result.push([code, amount].join(" "));
	}

	// 12.34$ 12.34€
	var symbolSuffixMatches = msg.matchAll(/(\d+(?:\.\d{1,2})?)\s?([€$])/g);
	for (match of symbolSuffixMatches) {
		var code = currencySymbolToCode(match[2]);
		var amount = Number.parseFloat(match[1]);
		result.push([code, amount].join(" "));
	}

	// GBP 12.34
	var codePrefixMatches = msg.matchAll(/(?<!\w)([a-zA-Z]{3})\s?(\d+(?:\.\d{1,2})?)/g);
	for (match of codePrefixMatches) {
		var code = match[1].toUpperCase();
		var amount = Number.parseFloat(match[2]);
		result.push([code, amount].join(" "));
	}

	// 12.34 GBP
	var codeSuffixMatches = msg.matchAll(/(\d+(?:\.\d{1,2})?)\s?([a-zA-Z]{3})(?!\w)/g);
	for (match of codeSuffixMatches) {
		var code = match[2].toUpperCase();
		var amount = Number.parseFloat(match[1]);
		result.push([code, amount].join(" "));
	}

	// Strip out duplicates
	result = [... new Set(result)];

	// return the array of strings, each in the format of "GBP 12.34"
	return result;
}

function currencySymbolToCode(symbol) {
	if (symbol == "£") {
		return "GBP";
	} else if (symbol == "€") {
		return "EUR";
	} else if (symbol == "$") {
		return "USD";
	}
}


// DISCORD LOGIN //
client.login(process.env.DISCORD_TOKEN);
