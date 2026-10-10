# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import asyncio
import logging
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, InlineQuery, InlineQueryResultPhoto, Message
from aiogram.utils.chat_action import ChatActionSender

from config import token, start_text, help_text

from animals import Animals, Unavailable, close_session, warm_up

logging.basicConfig(format=u'[%(asctime)s] %(levelname)+8s \t\t \
					[LINE:%(lineno)+3s] \t %(message)s',
					level=logging.INFO)

# The dispatcher holds the handlers and needs no bot, so importing this module
# (the tests do) works without a token. The Bot is only made in main().
dp = Dispatcher()

@dp.message(CommandStart())
async def process_start_command(msg: Message):
	# start_text already carries real emoji, so the emojize() that used to wrap
	# it returned the string unchanged. aiogram.utils.emoji is deprecated on top
	# of that, and raises TypeError against any current release of `emoji`.
	await msg.reply(start_text)

@dp.message(Command('help'))
async def process_help_command(msg: Message):
	await msg.reply(help_text, parse_mode=ParseMode.HTML)

# What a query has to contain to ask for one animal only. Anything else, the
# empty query included, gets some of each.
INLINE_WORDS = {
	"cat": ("кот", "кош", "cat", "kitt"),
	"dog": ("соб", "пёс", "пес", "щен", "dog", "pup"),
}
INLINE_RESULTS = 4

@dp.inline_query()
async def inline_echo(iq: InlineQuery):
	query = iq.query.lower()
	kinds = [kind for kind, words in INLINE_WORDS.items() if any(w in query for w in words)]
	if len(kinds) != 1:
		kinds = ["cat", "dog"]
	picks = (kinds * INLINE_RESULTS)[:INLINE_RESULTS]
	# Straight from the pools, so normally nothing here waits on the network.
	got = await asyncio.gather(
		*((Animals.give_me_a_cat if kind == "cat" else Animals.give_me_a_dog)() for kind in picks),
		return_exceptions=True,
	)
	results = []
	for kind, item in zip(picks, got):
		if isinstance(item, Unavailable):
			logging.warning("inline: no source for a %s: %s", kind, item)
			continue
		if isinstance(item, Exception):
			logging.error("inline: could not get a %s", kind, exc_info=item)
			continue
		photo_url, caption = item
		results.append(InlineQueryResultPhoto(
			# Telegram wants a string of 1-64 bytes here; this was a float
			# straight out of random.uniform.
			id = str(uuid.uuid4()),
			photo_url = photo_url,
			thumbnail_url = photo_url,
			title = "😺" if kind == "cat" else "🐶",
			caption = caption
		))
	# Answered even when empty: an unanswered inline query leaves the client
	# spinning.
	await iq.answer(results=results, cache_time = 1)

async def send_animal(msg: Message, kind):
	if kind == "cat":
		fetch, unavailable = Animals.give_me_a_cat, "Котики сейчас недоступны 😿\nПопробуйте через минуту!"
	else:
		fetch, unavailable = Animals.give_me_a_dog, "Собачки сейчас недоступны 🐶\nПопробуйте через минуту!"
	try:
		# "Sending a photo..." goes out alongside the photo rather than ahead of
		# it. Awaited first, it held every picture back by a Telegram round trip;
		# this way it still shows while Telegram downloads the picture.
		async with ChatActionSender.upload_photo(
			bot=msg.bot, chat_id=msg.chat.id, message_thread_id=msg.message_thread_id,
		):
			photo_url, caption = await fetch()
			# One photo is a sendPhoto. sendMediaGroup is documented for albums of
			# 2-10 items, and aiogram 3 has no MediaGroup to build one from anyway.
			await msg.reply_photo(photo_url, caption=caption)
	except Unavailable as e:
		# Every source is down. Saying so tells people a retry right now will not
		# help; the pool has already logged why each source failed.
		logging.warning("no source for a %s: %s", kind, e)
		await msg.reply(unavailable)
	except Exception:
		# print() sent the traceback nowhere useful while logging was already
		# configured, and swallowed the stack entirely.
		logging.exception("could not send a %s", kind)
		await msg.reply("Что-то пошло не так...\nПопробуйте снова!")

# Commands work where the words cannot: in a group, a bot in Telegram's default
# privacy mode is only shown commands, never a plain "котик".
@dp.message(Command('cat'))
async def cat_command(msg: Message):
	await send_animal(msg, "cat")

@dp.message(Command('dog'))
async def dog_command(msg: Message):
	await send_animal(msg, "dog")

KEYWORDS = {"котик": "cat", "собачка": "dog"}

# aiogram 2 handed a bare message_handler() text messages only. aiogram 3 hands
# a bare handler every message, and a sticker or a photo has no .text to lower().
@dp.message(F.text)
async def kotik(msg: Message):
	kind = KEYWORDS.get(msg.text.lower().strip())
	if kind:
		await send_animal(msg, kind)

# The menu Telegram shows next to the input field.
COMMANDS = [
	BotCommand(command="cat", description="Случайный котик"),
	BotCommand(command="dog", description="Случайная собачка"),
	BotCommand(command="help", description="Как пользоваться ботом"),
]

async def set_commands(bot: Bot):
	# The menu is a convenience; not having one is no reason to refuse to start.
	try:
		await bot.set_my_commands(COMMANDS)
	except TelegramAPIError:
		logging.warning("could not set the command menu", exc_info=True)

# warm_up only starts the fetches, so the menu is set while the pools fill.
dp.startup.register(warm_up)
dp.startup.register(set_commands)
dp.shutdown.register(close_session)

async def main():
	if not token:
		raise SystemExit("BOT_TOKEN is not set. Get one from @BotFather and export it.")
	# `async with` closes the HTTP session even when the first call fails, as
	# it does with a revoked token.
	#async with Bot(token=token, session=AiohttpSession(proxy="http://proxy.server:3128")) as bot:
	async with Bot(token=token) as bot:
		# aiogram 2's skip_updates=True: whatever queued up while the bot was
		# down is dropped rather than answered all at once.
		await bot.delete_webhook(drop_pending_updates=True)
		await dp.start_polling(bot)

if __name__ == '__main__':
	asyncio.run(main())
