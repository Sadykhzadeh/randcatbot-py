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
import time

import aiohttp

from config import cap_mas, dog_mas

# These two calls used to go through `requests`, which blocks the thread it
# runs on. Made from inside a coroutine, that meant an API which stopped
# answering did not make one reply slow - it stopped the bot answering anybody
# for the length of the timeout. aiohttp is already pulled in by aiogram, so
# the fetch can simply be awaited.
# Per source: with a fallback behind each one, a hung API used to cost the
# full ten seconds; two tries at five keep the worst case where it was.
TIMEOUT = aiohttp.ClientTimeout(total=5)

# Both APIs hand out ten pictures per request for the price of one.
CAT_API = "https://api.thecatapi.com/v1/images/search?limit=10"
DOG_API = "https://dog.ceo/api/breeds/image/random/10"

# Fallbacks, asked only when the API above them fails. Cat as a Service lists
# about 2000 cats with their types; the offset keeps a batch from always
# being the same ten. random.dog serves one at a time, and videos unless told.
CATAAS_API = "https://cataas.com/api/cats?limit=10&skip={}"
CATAAS_IMAGE = "https://cataas.com/cat/{}"
RANDOMDOG_API = "https://random.dog/woof.json?include=jpg"

# Telegram fetches a photo sent by URL, or offered in inline mode, only up to
# 5 MB. random.dog keeps camera originals, and about one in thirty is bigger.
MAX_PHOTO_BYTES = 5_000_000

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


async def _cataas():
	cats = await _get_json(CATAAS_API.format(random.randrange(1000)))
	return [CATAAS_IMAGE.format(c["id"]) for c in cats if c["mimetype"] == "image/jpeg"]


async def _randomdog():
	# One picture a request, and it says how big it is: a few tries find one
	# Telegram will take.
	for _ in range(3):
		dog = await _get_json(RANDOMDOG_API)
		url, size = dog["url"], dog.get("fileSizeBytes", 0)
		if size <= MAX_PHOTO_BYTES:
			return _jpegs([url])
		log.info("random.dog: %s is %d bytes, over the limit", url, size)
	return []


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

	# Seconds after every source failed during which requests are told so at
	# once instead of each waiting on the same failures again.
	REST = 30

	def __init__(self, sources, low=3, clock=time.monotonic):
		self._sources = sources
		self._low = low
		self._clock = clock
		self._urls = collections.deque()
		self._fetch = None
		self._down_until = 0

	async def get(self):
		while not self._urls:
			if self._clock() < self._down_until or not await asyncio.shield(self._start_fetch()):
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
		self._down_until = self._clock() + self.REST
		return False

	async def close(self):
		if self._fetch is not None and not self._fetch.done():
			self._fetch.cancel()
			with contextlib.suppress(asyncio.CancelledError):
				await self._fetch
		self._fetch = None


# Every fill starts from the first source again, so a fallback is only used
# for as long as the main API is actually down.
cats = Pool((_thecatapi, _cataas))
dogs = Pool((_dogceo, _randomdog))


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
