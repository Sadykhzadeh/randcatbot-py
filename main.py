# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import asyncio
import contextlib
import logging
import re
import uuid

# Has to come before the first aiogram import; see lazy_models.py.
import lazy_models  # noqa: F401

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart, ExceptionTypeFilter
from aiogram.types import (
	BotCommand, CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup,
	InlineQuery, InlineQueryResultPhoto, Message,
)
from aiogram.utils.chat_action import ChatActionSender

from config import token, start_text, help_text

from animals import Animals, Unavailable, close_session, warm_up
from throttle import ALLOW, WARN, Throttle

# The module as well as the line: a warning can come from here, animals.py or
# aiogram, and a line number alone does not say which.
logging.basicConfig(format='[%(asctime)s] %(levelname)8s [%(module)s:%(lineno)d] %(message)s',
					level=logging.INFO)

# The dispatcher holds the handlers and needs no bot, so importing this module
# (the tests do) works without a token. The Bot is only made in main().
dp = Dispatcher()

# Every answer is a reply, and Telegram refuses a reply to a message that is
# gone - deleted by its sender, or by a group's admin bot the moment a command
# arrives - unless told to send it anyway.
DEFAULTS = DefaultBotProperties(allow_sending_without_reply=True)

@dp.message(CommandStart())
async def process_start_command(msg: Message):
	# start_text already carries real emoji, so the emojize() that used to wrap
	# it returned the string unchanged. aiogram.utils.emoji is deprecated on top
	# of that, and raises TypeError against any current release of `emoji`.
	await msg.reply(start_text)

@dp.message(Command('help'))
async def process_help_command(msg: Message):
	# Inline mode starts with the bot's name, and a copy of the bot run from
	# this repository is not @randcatbot. aiogram asked Telegram for it when
	# polling started, so this costs no request.
	me = await msg.bot.me()
	await msg.reply(help_text.format(username=me.username), parse_mode=ParseMode.HTML)

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

# One picture a second per person and chat: Telegram asks bots to keep to about
# one message a second in a chat, and past that answers with flood waits. The
# key includes the chat because anonymous group admins all post as one user.
limiter = Throttle(1.0)

class UploadStatus(ChatActionSender):
	'''
	"Sending a photo..." for as long as the photo takes to go out.

	aiogram's sender lets a refused sendChatAction - under flood control, or in
	a chat the bot was just removed from - end its background task with the
	error, and nothing awaits that task, so asyncio logs the error as an
	unhandled traceback. The status is cosmetic: failing to show it is not an
	error, and the photo's own outcome is handled in send_picture.
	'''

	async def _worker(self):
		with contextlib.suppress(TelegramAPIError):
			await super()._worker()

SLOW_DOWN = "Не так быстро 🐾\nОдна картинка в секунду."

# The button under every picture, for one more of the same.
MORE = {
	kind: InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="more:" + kind)]])
	for kind, text in (("cat", "🐱 Ещё котика"), ("dog", "🐶 Ещё собачку"))
}

# What Telegram answers when it cannot use the picture behind a URL: gone,
# broken, not an image after all, or of a size it does not take. Another
# picture from the pool will usually do.
UNUSABLE_PHOTO = (
	"failed to get HTTP URL content", "wrong file identifier/HTTP URL specified",
	"wrong type of the web page content", "IMAGE_PROCESS_FAILED", "PHOTO_INVALID_DIMENSIONS",
)
PHOTO_TRIES = 3

async def send_animal(msg: Message, kind):
	verdict = limiter.hit((msg.chat.id, msg.from_user.id if msg.from_user else None))
	if verdict != ALLOW:
		if verdict == WARN:
			await msg.reply(SLOW_DOWN)
		return
	await send_picture(msg, kind, reply=True)

async def send_picture(msg, kind, reply):
	# A reply to the message that asked for it, or, for a button, simply into
	# the chat: replying to the picture before would chain them all together.
	answer, answer_photo = (msg.reply, msg.reply_photo) if reply else (msg.answer, msg.answer_photo)
	if kind == "cat":
		fetch, unavailable = Animals.give_me_a_cat, "Котики сейчас недоступны 😿\nПопробуйте через минуту!"
	else:
		fetch, unavailable = Animals.give_me_a_dog, "Собачки сейчас недоступны 🐶\nПопробуйте через минуту!"
	try:
		# "Sending a photo..." goes out alongside the photo rather than ahead of
		# it. Awaited first, it held every picture back by a Telegram round trip;
		# this way it still shows while Telegram downloads the picture.
		async with UploadStatus.upload_photo(
			# Telegram can hand a button's message over as an
			# InaccessibleMessage, which has no thread.
			bot=msg.bot, chat_id=msg.chat.id, message_thread_id=getattr(msg, "message_thread_id", None),
		):
			for tries_left in reversed(range(PHOTO_TRIES)):
				photo_url, caption = await fetch()
				try:
					# One photo is a sendPhoto. sendMediaGroup is documented for albums
					# of 2-10 items, and aiogram 3 has no MediaGroup to build one from
					# anyway.
					await answer_photo(photo_url, caption=caption, reply_markup=MORE[kind])
					break
				except TelegramBadRequest as e:
					if not tries_left or not any(s in e.message for s in UNUSABLE_PHOTO):
						raise
					logging.warning("Telegram could not use %s: %s", photo_url, e.message)
	except Unavailable as e:
		# Every source is down. Saying so tells people a retry right now will not
		# help; the pool has already logged why each source failed.
		logging.warning("no source for a %s: %s", kind, e)
		await answer(unavailable)
	except (TelegramRetryAfter, TelegramForbiddenError):
		# Left to the error handlers below: an apology would only be refused
		# the same way.
		raise
	except Exception as e:
		if isinstance(e, TelegramBadRequest) and "not enough rights to send photos" in e.message:
			# The group does not let its members send media, and the bot is a
			# member like any other: trying again will never work, but text
			# still gets through.
			logging.warning("no right to send photos in chat %s", msg.chat.id)
			await answer("Здесь мне нельзя отправлять фото 😿\nАдминистраторы могут разрешить это в настройках группы.")
			return
		# print() sent the traceback nowhere useful while logging was already
		# configured, and swallowed the stack entirely.
		logging.exception("could not send a %s", kind)
		await answer("Что-то пошло не так...\nПопробуйте снова!")

# Commands work where the words cannot: in a group, a bot in Telegram's default
# privacy mode is only shown commands, never a plain "котик".
@dp.message(Command('cat'))
async def cat_command(msg: Message):
	await send_animal(msg, "cat")

@dp.message(Command('dog'))
async def dog_command(msg: Message):
	await send_animal(msg, "dog")

@dp.callback_query(F.data.in_({"more:cat", "more:dog"}), F.message)
async def more_button(cq: CallbackQuery):
	kind = cq.data.removeprefix("more:")
	# The same limit as for asking in words, with the refusal shown under the
	# button rather than sent into the chat.
	if limiter.hit((cq.message.chat.id, cq.from_user.id)) != ALLOW:
		await cq.answer(SLOW_DOWN)
		return
	# Answered first, so the button stops spinning while the picture goes out.
	await cq.answer()
	await send_picture(cq.message, kind, reply=False)

KEYWORDS = {"котик": "cat", "собачка": "dog"}
# What people put around the word: "Котик!", "котик)", "собачка 🐶".
AROUND_WORD = re.compile(r"^\W+|\W+$")

# aiogram 2 handed a bare message_handler() text messages only. aiogram 3 hands
# a bare handler every message, and a sticker or a photo has no .text to lower().
@dp.message(F.text)
async def kotik(msg: Message):
	kind = KEYWORDS.get(AROUND_WORD.sub("", msg.text.lower()))
	if kind:
		await send_animal(msg, kind)

# Flood control: Telegram refuses anything more into a chat until the wait is
# over. A busy group gets there even with each person limited, and then the
# "slow down", /help and inline answers are refused as well as photos. What
# was being sent is dropped; nothing else is sent, it would be refused too.
@dp.errors(ExceptionTypeFilter(TelegramRetryAfter))
async def flood_control(event: ErrorEvent):
	e = event.exception
	chat = getattr(e.method, "chat_id", None)
	logging.warning("flood control for %s s, %s%s was dropped", e.retry_after,
					type(e.method).__name__, f" to chat {chat}" if chat else "")

# The bot may not write into the chat at all: a group's admins muted it, or it
# was removed or blocked while an answer was on its way. It still sees the
# commands, but nothing it sends there gets through, the apology included.
@dp.errors(ExceptionTypeFilter(TelegramForbiddenError))
@dp.errors(ExceptionTypeFilter(TelegramBadRequest), F.exception.message.contains("not enough rights to send"))
async def cannot_write(event: ErrorEvent):
	e = event.exception
	logging.warning("%s to chat %s was refused: %s", type(e.method).__name__,
					getattr(e.method, "chat_id", None), e.message)

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
	async with Bot(token=token, default=DEFAULTS) as bot:
		# aiogram 2's skip_updates=True: whatever queued up while the bot was
		# down is dropped rather than answered all at once.
		await bot.delete_webhook(drop_pending_updates=True)
		await dp.start_polling(bot)

if __name__ == '__main__':
	asyncio.run(main())
