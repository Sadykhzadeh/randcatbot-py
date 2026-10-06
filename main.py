# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import logging
import uuid

from aiogram import Bot, types
from aiogram.utils import executor
from aiogram.dispatcher import Dispatcher
from aiogram.types import ParseMode
from aiogram.types import InlineQuery, InlineQueryResultPhoto
from aiogram.contrib.middlewares.logging import LoggingMiddleware

from config import token, start_text, help_text

from animals import Animals, close_session

logging.basicConfig(format=u'[%(asctime)s] %(levelname)+8s \t\t \
					[LINE:%(lineno)+3s] \t %(message)s',
					level=logging.INFO)

if not token:
	raise SystemExit("BOT_TOKEN is not set. Get one from @BotFather and export it.")

bot = Bot(token=token)
#bot = Bot(token=token, proxy = "http://proxy.server:3128")
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

@dp.message_handler(commands=['start'])
async def process_start_command(msg: types.Message):
	# start_text already carries real emoji, so the emojize() that used to wrap
	# it returned the string unchanged. aiogram.utils.emoji is deprecated on top
	# of that, and raises TypeError against any current release of `emoji`.
	await msg.reply(start_text)

@dp.message_handler(commands=['help'])
async def process_help_command(msg: types.Message):
	await msg.reply(help_text, parse_mode=ParseMode.HTML)

@dp.inline_handler()
async def inline_echo(iq: InlineQuery):
	try:
		photo_url, caption = await Animals.give_me_a_cat()
	except Exception:
		# An unanswered inline query used to leave the client spinning.
		logging.exception("inline cat request failed")
		await bot.answer_inline_query(iq.id, results=[], cache_time=1)
		return
	cat = InlineQueryResultPhoto(
		# Telegram wants a string of 1-64 bytes here; this was a float straight
		# out of random.uniform.
		id = str(uuid.uuid4()),
		photo_url = photo_url,
		thumb_url = photo_url,
		title = "😺",
		caption = caption
	)
	await bot.answer_inline_query(iq.id, results=[cat], cache_time = 1)

@dp.message_handler()
async def kotik(msg: types.Message):
	what_we_want = msg.text.lower().strip()
	try:
		if what_we_want == "котик":
			await types.ChatActions.upload_photo()
			photo_url, caption = await Animals.give_me_a_cat()
		elif what_we_want == "собачка":
			await types.ChatActions.upload_photo()
			photo_url, caption = await Animals.give_me_a_dog()
		else:
			return
		media = types.MediaGroup()
		media.attach_photo(photo_url, caption)
		await msg.reply_media_group(media = media)
	except Exception:
		# print() sent the traceback nowhere useful while logging was already
		# configured, and swallowed the stack entirely.
		logging.exception("could not answer %r", what_we_want)
		await msg.reply("Что-то пошло не так...\nПопробуйте снова!")

async def on_shutdown(_):
	await close_session()

if __name__ == '__main__':
	executor.start_polling(dp, skip_updates=True, on_shutdown=on_shutdown)
