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
	'''Answers like the four APIs do, ten pictures a request where they batch.'''

	def __init__(self):
		self.hits = collections.Counter()
		self.skips = []
		# what random.dog reports as each picture's size, in turn
		self.dog_sizes = iter(())
		self.serial = itertools.count()
		self.routes = {
			"cats": self.thecatapi, "cataas": self.cataas,
			"dogs": self.dogceo, "randomdog": self.randomdog,
		}
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

	async def cataas(self, request):
		self.skips.append(int(request.query["skip"]))
		types = ["image/jpeg"] * 8 + ["image/png", "image/gif"]
		return web.json_response([
			{"id": f"k{n}", "mimetype": t, "tags": []}
			for n, t in zip(self.serial, types)
		])

	async def randomdog(self, request):
		return web.json_response({
			"fileSizeBytes": next(self.dog_sizes, 86906),
			"url": f"https://random.dog/r{next(self.serial)}.JPG",
		})

	@staticmethod
	async def only_gifs(request):
		return web.json_response([{"id": n, "url": f"https://cdn.example/g{n}.gif"} for n in range(10)])

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
			("CATAAS_API", self.up.url("cataas") + "?skip={}"),
			("DOG_API", self.up.url("dogs")),
			("RANDOMDOG_API", self.up.url("randomdog")),
			("TIMEOUT", animals.aiohttp.ClientTimeout(total=0.5)),
		):
			patcher = patch.object(animals, name, value)
			patcher.start()
			self.addCleanup(patcher.stop)
		# the same sources, in the same order, as the bot's own pools
		self.now = 0.0
		self.cats = animals.Pool(animals.cats._sources, clock=lambda: self.now)
		self.dogs = animals.Pool(animals.dogs._sources, clock=lambda: self.now)

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

	async def test_the_fallback_is_not_asked_while_the_main_api_answers(self):
		await self.cats.get()
		await self.dogs.get()
		self.assertEqual(self.up.hits["cataas"], 0)
		self.assertEqual(self.up.hits["randomdog"], 0)

	async def test_an_error_status_falls_back_to_cataas(self):
		self.up.routes["cats"] = FakeUpstream.failing(503)
		urls = [await self.cats.get() for _ in range(8)]
		self.assertTrue(all(u.startswith("https://cataas.com/cat/k") for u in urls), urls)
		# the PNG and the GIF in the listing are skipped
		self.assertEqual(self.up.hits["cataas"], 1)
		self.assertTrue(all(0 <= skip < 1000 for skip in self.up.skips))

	async def test_a_page_that_is_not_json_falls_back_to_random_dog(self):
		self.up.routes["dogs"] = FakeUpstream.garbage
		url = await self.dogs.get()
		self.assertRegex(url, r"^https://random\.dog/r\d+\.JPG$")

	async def test_a_random_dog_too_big_for_telegram_is_skipped(self):
		self.up.routes["dogs"] = FakeUpstream.failing(503)
		self.up.dog_sizes = iter([11_476_001, 5_476_798, 2_770_862])
		url = await self.dogs.get()
		self.assertEqual(self.up.hits["randomdog"], 3)
		self.assertRegex(url, r"^https://random\.dog/r\d+\.JPG$")
		self.assertEqual(len(self.dogs._urls), 0)

	async def test_random_dog_giving_only_big_pictures_counts_as_down(self):
		self.up.routes["dogs"] = FakeUpstream.failing(503)
		self.up.dog_sizes = itertools.repeat(6_109_341)
		with self.assertRaises(animals.Unavailable):
			await self.dogs.get()
		self.assertEqual(self.up.hits["randomdog"], 3)

	async def test_a_batch_with_no_jpeg_in_it_falls_back(self):
		self.up.routes["cats"] = FakeUpstream.only_gifs
		self.assertTrue((await self.cats.get()).startswith("https://cataas.com/"))

	async def test_a_hung_api_is_given_up_on_for_the_fallback(self):
		self.up.routes["cats"] = FakeUpstream.hanging
		loop = asyncio.get_running_loop()
		started = loop.time()
		self.assertTrue((await self.cats.get()).startswith("https://cataas.com/"))
		self.assertLess(loop.time() - started, 2)

	async def test_with_every_source_down_it_is_unavailable(self):
		self.up.routes["cats"] = FakeUpstream.failing(500)
		self.up.routes["cataas"] = FakeUpstream.hanging
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()
		self.up.routes["dogs"] = FakeUpstream.garbage
		self.up.routes["randomdog"] = FakeUpstream.failing(404)
		with self.assertRaises(animals.Unavailable):
			await self.dogs.get()

	async def test_a_failing_source_is_logged_in_one_line(self):
		self.up.routes["cats"] = FakeUpstream.hanging
		self.up.routes["cataas"] = FakeUpstream.failing(503)
		with self.assertLogs("animals", level="WARNING") as logs:
			with self.assertRaises(animals.Unavailable):
				await self.cats.get()
		self.assertEqual([r.getMessage().split(",")[0] for r in logs.records], [
			"_thecatapi failed: TimeoutError",
			"_cataas failed: ClientResponseError: 503",
		])
		self.assertTrue(all(r.exc_info is None for r in logs.records))

	async def test_the_main_api_is_preferred_again_once_it_recovers(self):
		self.up.routes["cats"] = FakeUpstream.failing(500)
		self.up.routes["cataas"] = FakeUpstream.failing(500)
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()
		self.up.routes["cats"] = self.up.thecatapi
		self.up.routes["cataas"] = self.up.cataas
		self.now += animals.Pool.REST
		self.assertTrue((await self.cats.get()).startswith("https://cdn.example/"))

	async def test_right_after_every_source_failed_requests_are_refused_at_once(self):
		self.up.routes["cats"] = FakeUpstream.hanging
		self.up.routes["cataas"] = FakeUpstream.hanging
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()
		hits = sum(self.up.hits.values())
		loop = asyncio.get_running_loop()
		started = loop.time()
		self.now += animals.Pool.REST - 1
		for _ in range(3):
			with self.assertRaises(animals.Unavailable):
				await self.cats.get()
		self.assertLess(loop.time() - started, 0.1)
		self.assertEqual(sum(self.up.hits.values()), hits)
		# the rest is over: both are asked again
		self.now += 1
		with self.assertRaises(animals.Unavailable):
			await self.cats.get()
		self.assertEqual(sum(self.up.hits.values()), hits + 2)

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
