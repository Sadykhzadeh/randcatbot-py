# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import asyncio
import logging
import requests
import random

from aiogram import Bot, types
from aiogram.utils import executor
from aiogram.utils.emoji import emojize
from aiogram.dispatcher import Dispatcher
from aiogram.types.message import ContentType
from aiogram.utils.markdown import text, bold, italic, code, pre
from aiogram.types import ParseMode, InputMediaPhoto, InputMediaVideo, ChatActions
from aiogram.types import InlineQuery, InlineQueryResultPhoto
from aiogram.contrib.middlewares.logging import LoggingMiddleware

from config import token, start_text, \
			help_text, cap_mas, dog_mas

from animals import Animals

logging.basicConfig(format=u'[%(asctime)s] %(levelname)+8s \t\t \
					[LINE:%(lineno)+3s] \t %(message)s',
					level=logging.INFO)

bot = Bot(token=token)
#bot = Bot(token=token, proxy = "http://proxy.server:3128")
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

@dp.message_handler(commands=['start'])
async def process_start_command(msg: types.Message):
	await msg.reply(text(emojize(start_text)))

@dp.message_handler(commands=['help'])
async def process_help_command(msg: types.Message):
	await msg.reply(text(emojize(help_text)), parse_mode=ParseMode.HTML)

@dp.inline_handler()
async def inline_echo(iq: InlineQuery):
	result_id = random.uniform(0,2384723684723684)
	catt = Animals.give_me_a_cat()
	cat = InlineQueryResultPhoto(
		id = result_id,
		photo_url = catt[0],
		thumb_url = catt[0],
		title = "😺",
		caption = catt[1]
	)
	await bot.answer_inline_query(iq.id, results=[cat], cache_time = 1)

@dp.message_handler()
async def kotik(msg: types.Message):
	what_we_want = msg.text.lower()
	try:
		if what_we_want == "котик":
			await types.ChatActions.upload_photo()
			cat = Animals.give_me_a_cat()
			cat_n_caption = types.MediaGroup()
			cat_n_caption.attach_photo(cat[0], cat[1])
			await msg.reply_media_group(media = cat_n_caption)
		if what_we_want == "собачка":
			await types.ChatActions.upload_photo()
			dog = Animals.give_me_a_dog()
			dog_n_caption = types.MediaGroup()
			dog_n_caption.attach_photo(dog[0], dog[1])
			await msg.reply_media_group(media = dog_n_caption)
	except Exception as e:
		print(e)
		await msg.reply(text("Что-то пошло не так...\nПопробуйте снова!"))

if __name__ == '__main__':
	executor.start_polling(dp, skip_updates=True)