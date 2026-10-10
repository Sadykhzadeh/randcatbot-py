# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import asyncio
import collections
import contextlib
import logging
import random

import aiohttp

from config import cap_mas, dog_mas

# These two calls used to go through `requests`, which blocks the thread it
# runs on. Made from inside a coroutine, that meant an API which stopped
# answering did not make one reply slow - it stopped the bot answering anybody
# for the length of the timeout. aiohttp is already pulled in by aiogram, so
# the fetch can simply be awaited.
TIMEOUT = aiohttp.ClientTimeout(total=10)

# Both APIs hand out ten pictures per request for the price of one.
CAT_API = "https://api.thecatapi.com/v1/images/search?limit=10"
DOG_API = "https://dog.ceo/api/breeds/image/random/10"

log = logging.getLogger(__name__)

_session = None


def _get_session():
	# One session for the life of the process, so connections are reused instead
	# of paying for a TCP and TLS handshake per picture.
	global _session
	if _session is None or _session.closed:
		_session = aiohttp.ClientSession(timeout=TIMEOUT)
	return _session


async def _get_json(url):
	async with _get_session().get(url) as response:
		response.raise_for_status()
		return await response.json(content_type=None)


def _jpegs(urls):
	# Telegram documents inline photo results as JPEG only. Without an API key
	# thecatapi ignores its mime_types filter, and about one picture in ten is
	# a GIF or a PNG.
	return [u for u in urls if u.lower().endswith((".jpg", ".jpeg"))]


async def _thecatapi():
	return _jpegs(item["url"] for item in await _get_json(CAT_API))


async def _dogceo():
	return _jpegs((await _get_json(DOG_API))["message"])


class Unavailable(Exception):
	'''No source could give a picture.'''


# What a source that answers with garbage, an error status or nothing at all
# raises. Anything else is a bug and is left to propagate.
_SOURCE_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError, LookupError, TypeError, ValueError)


class Pool:
	'''
	Picture URLs fetched ahead of the requests for them.

	Each upstream request brings a batch, and the pool is topped up in the
	background before it runs dry, so a request is normally answered without
	waiting on an upstream API at all. Concurrent requests that do find it
	empty share the one fetch in flight rather than each starting their own.
	'''

	def __init__(self, sources, low=3):
		self._sources = sources
		self._low = low
		self._urls = collections.deque()
		self._fetch = None

	async def get(self):
		while not self._urls:
			if not await asyncio.shield(self._start_fetch()):
				raise Unavailable(", ".join(s.__name__ for s in self._sources))
		url = self._urls.popleft()
		if len(self._urls) < self._low:
			self._start_fetch()
		return url

	def warm_up(self):
		self._start_fetch()

	def _start_fetch(self):
		if self._fetch is None or self._fetch.done():
			self._fetch = asyncio.ensure_future(self._fill())
		return self._fetch

	async def _fill(self):
		for source in self._sources:
			try:
				urls = await source()
			except _SOURCE_ERRORS:
				log.warning("%s failed", source.__name__, exc_info=True)
				continue
			if urls:
				self._urls.extend(urls)
				return True
			log.warning("%s gave no usable picture", source.__name__)
		return False

	async def close(self):
		if self._fetch is not None and not self._fetch.done():
			self._fetch.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await self._fetch
		self._fetch = None


cats = Pool((_thecatapi,))
dogs = Pool((_dogceo,))


async def warm_up():
	# Fill both pools in the background as the bot starts, so even the first
	# request after a restart does not wait on an upstream API.
	cats.warm_up()
	dogs.warm_up()


async def close_session():
	global _session
	for pool in (cats, dogs):
		await pool.close()
	if _session is not None and not _session.closed:
		await _session.close()
	_session = None


class Animals():
	@staticmethod
	async def give_me_a_cat():
		# `cap_mas[int(random.uniform(0, len(cap_mas)))]` could index one past
		# the end of the list: random.uniform is documented as possibly
		# returning its upper bound.
		caption = random.choice(cap_mas)
		return [await cats.get(), caption]

	@staticmethod
	async def give_me_a_dog():
		caption = random.choice(dog_mas)
		return [await dogs.get(), caption]
