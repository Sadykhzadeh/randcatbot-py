# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import random

import aiohttp

from config import cap_mas, dog_mas

# These two calls used to go through `requests`, which blocks the thread it
# runs on. Made from inside a coroutine, that meant an API which stopped
# answering did not make one reply slow - it stopped the bot answering anybody
# for the length of the timeout. aiohttp is already pulled in by aiogram, so
# the fetch can simply be awaited.
TIMEOUT = aiohttp.ClientTimeout(total=10)

CAT_API = "https://api.thecatapi.com/v1/images/search"
DOG_API = "https://dog.ceo/api/breeds/image/random"

_session = None


def _get_session():
	# One session for the life of the process, so connections are reused instead
	# of paying for a TCP and TLS handshake per picture.
	global _session
	if _session is None or _session.closed:
		_session = aiohttp.ClientSession(timeout=TIMEOUT)
	return _session


async def close_session():
	global _session
	if _session is not None and not _session.closed:
		await _session.close()
	_session = None


async def _get_json(url):
	async with _get_session().get(url) as response:
		response.raise_for_status()
		return await response.json(content_type=None)


class Animals():
	@staticmethod
	async def give_me_a_cat():
		# `cap_mas[int(random.uniform(0, len(cap_mas)))]` could index one past
		# the end of the list: random.uniform is documented as possibly
		# returning its upper bound.
		caption = random.choice(cap_mas)
		payload = await _get_json(CAT_API)
		return [payload[0]['url'], caption]

	@staticmethod
	async def give_me_a_dog():
		caption = random.choice(dog_mas)
		payload = await _get_json(DOG_API)
		return [payload['message'], caption]
