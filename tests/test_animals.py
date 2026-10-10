'''
The picture pools, against a local HTTP server standing in for the animal
APIs, so the real aiohttp code path runs: status codes, JSON parsing,
timeouts and how many requests actually go out.
'''

import asyncio
import collections
import itertools
import logging
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

import animals
from config import cap_mas

logging.getLogger("animals").setLevel(logging.CRITICAL)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
# the test loop runs in asyncio debug mode, which announces every server
logging.getLogger("asyncio").setLevel(logging.ERROR)


class FakeUpstream:
	'''Answers like thecatapi and dog.ceo, ten pictures a request by default.'''

	def __init__(self):
		self.hits = collections.Counter()
		self.serial = itertools.count()
		self.routes = {"cats": self.thecatapi, "dogs": self.dogceo}
		app = web.Application()
		app.router.add_get("/{name}", self.handle)
		self.server = TestServer(app)

	async def handle(self, request):
		name = request.match_info["name"]
		self.hits[name] += 1
		return await self.routes[name](request)

	def url(self, name):
		return str(self.server.make_url("/" + name))

	async def thecatapi(self, request):
		# one GIF and one PNG per batch, as thecatapi really serves them
		exts = ["jpg"] * 8 + ["gif", "png"]
		return web.json_response([
			{"id": n, "url": f"https://cdn.example/c{n}.{ext}"}
			for n, ext in zip(self.serial, exts)
		])

	async def dogceo(self, request):
		return web.json_response({
			"message": [f"https://cdn.example/d{next(self.serial)}.jpg" for _ in range(10)],
			"status": "success",
		})

	@staticmethod
	def failing(status):
		async def route(request):
			return web.Response(status=status, text="no")
		return route

	@staticmethod
	async def garbage(request):
		return web.Response(text="<html>maintenance</html>", content_type="text/html")

	@staticmethod
	async def hanging(request):
		await asyncio.sleep(30)
		return web.json_response([])


class PoolTest(unittest.IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		self.up = FakeUpstream()
		await self.up.server.start_server()
		for name, value in (
			("CAT_API", self.up.url("cats")),
			("DOG_API", self.up.url("dogs")),
			("TIMEOUT", animals.aiohttp.ClientTimeout(total=0.5)),
		):
			patcher = patch.object(animals, name, value)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.cats = animals.Pool((animals._thecatapi,))
		self.dogs = animals.Pool((animals._dogceo,))

	async def asyncTearDown(self):
		await self.cats.close()
		await self.dogs.close()
		await animals.close_session()
		await self.up.server.close()

	async def settle(self):
		# let a background top-up run to completion
		for pool in (self.cats, self.dogs):
			if pool._fetch is not None:
				await pool._fetch

	async def test_one_request_serves_a_whole_batch(self):
		urls = [await self.cats.get() for _ in range(5)]
		self.assertEqual(self.up.hits["cats"], 1)
		self.assertEqual(len(set(urls)), 5)

	async def test_only_jpegs_are_kept(self):
		urls = [await self.cats.get() for _ in range(16)]
		self.assertTrue(all(u.endswith(".jpg") for u in urls), urls)

	async def test_the_pool_is_topped_up_before_it_runs_dry(self):
		for _ in range(6):  # 8 JPEGs in a batch, 2 left: below the low mark
			await self.cats.get()
		await self.settle()
		self.assertEqual(self.up.hits["cats"], 2)
		self.assertEqual(len(self.cats._urls), 10)

	async def test_concurrent_requests_on_an_empty_pool_share_one_fetch(self):
		urls = await asyncio.gather(*(self.dogs.get() for _ in range(5)))
		self.assertEqual(self.up.hits["dogs"], 1)
		self.assertEqual(len(set(urls)), 5)

	async def test_more_waiters_than_a_batch_holds_are_all_served(self):
		urls = await asyncio.gather(*(self.dogs.get() for _ in range(25)))
		self.assertEqual(len(set(urls)), 25)
		# three batches are needed; one more may be a top-up, not one per waiter
		self.assertLessEqual(self.up.hits["dogs"], 4)

	async def test_an_error_status_means_unavailable(self):
		self.up.routes["cats"] = FakeUpstream.failing(503)
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()

	async def test_a_page_that_is_not_json_means_unavailable(self):
		self.up.routes["dogs"] = FakeUpstream.garbage
		with self.assertRaises(animals.Unavailable):
			await self.dogs.get()

	async def test_an_upstream_that_hangs_is_given_up_on(self):
		self.up.routes["cats"] = FakeUpstream.hanging
		loop = asyncio.get_running_loop()
		started = loop.time()
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()
		self.assertLess(loop.time() - started, 2)

	async def test_a_failed_fetch_is_retried_on_the_next_request(self):
		self.up.routes["cats"] = FakeUpstream.failing(500)
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()
		self.up.routes["cats"] = self.up.thecatapi
		self.assertTrue(await self.cats.get())

	async def test_warm_up_fills_without_anyone_waiting(self):
		self.cats.warm_up()
		self.dogs.warm_up()
		await self.settle()
		self.assertEqual(len(self.cats._urls), 8)
		self.assertEqual(len(self.dogs._urls), 10)

	async def test_close_cancels_a_fetch_in_flight(self):
		self.up.routes["cats"] = FakeUpstream.hanging
		self.cats.warm_up()
		await asyncio.sleep(0.05)
		await self.cats.close()
		self.assertIsNone(self.cats._fetch)

	async def test_give_me_a_cat_pairs_a_picture_with_a_caption(self):
		with patch.object(animals, "cats", self.cats):
			url, caption = await animals.Animals.give_me_a_cat()
		self.assertTrue(url.startswith("https://cdn.example/"))
		self.assertIn(caption, cap_mas)


if __name__ == "__main__":
	unittest.main()
