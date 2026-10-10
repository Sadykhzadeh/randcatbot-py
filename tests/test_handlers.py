'''
The handlers, run through the real dispatcher against a bot that records what
it would have sent. No token and no network: the animal APIs are mocked out.
'''

import logging
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction, ParseMode

import main
from config import help_text, start_text
from tests.helpers import inline_query, make_bot, message, reply_target

logging.getLogger("aiogram").setLevel(logging.WARNING)

CAT = ["https://cdn.example/cat.jpg", "Красивый котик."]
DOG = ["https://cdn.example/dog.jpg", "Красивая собачка."]


class HandlerTest(unittest.IsolatedAsyncioTestCase):
	def setUp(self):
		self.bot, self.session = make_bot()
		self.cat = AsyncMock(return_value=CAT)
		self.dog = AsyncMock(return_value=DOG)
		for name, mock in (("give_me_a_cat", self.cat), ("give_me_a_dog", self.dog)):
			patcher = patch.object(main.Animals, name, mock)
			patcher.start()
			self.addCleanup(patcher.stop)

	async def feed(self, update):
		return await main.dp.feed_update(self.bot, update)


class CommandTest(HandlerTest):
	async def test_start_replies_with_the_greeting(self):
		update = message("/start")
		await self.feed(update)
		[sent] = self.session.sent("SendMessage")
		self.assertEqual(sent.text, start_text)
		self.assertEqual(reply_target(sent), update.message.message_id)

	async def test_help_is_sent_as_html(self):
		await self.feed(message("/help"))
		[sent] = self.session.sent("SendMessage")
		self.assertEqual(sent.text, help_text)
		self.assertEqual(sent.parse_mode, ParseMode.HTML)

	async def test_a_command_addressed_to_this_bot_in_a_group_works(self):
		await self.feed(message("/help@randcatbot", chat_type="supergroup"))
		[sent] = self.session.sent("SendMessage")
		self.assertEqual(sent.text, help_text)

	async def test_a_command_addressed_to_another_bot_is_left_alone(self):
		await self.feed(message("/help@otherbot", chat_type="supergroup"))
		self.assertEqual(self.session.sent("SendMessage"), [])


class KeywordTest(HandlerTest):
	async def test_kotik_replies_with_a_cat_photo(self):
		update = message("котик")
		await self.feed(update)
		[action] = self.session.sent("SendChatAction")
		self.assertEqual(action.action, ChatAction.UPLOAD_PHOTO)
		[photo] = self.session.sent("SendPhoto")
		self.assertEqual((photo.photo, photo.caption), tuple(CAT))
		self.assertEqual(photo.chat_id, update.message.chat.id)
		self.assertEqual(reply_target(photo), update.message.message_id)
		self.dog.assert_not_called()

	async def test_sobachka_ignores_case_and_surrounding_space(self):
		await self.feed(message("  Собачка \n"))
		[photo] = self.session.sent("SendPhoto")
		self.assertEqual((photo.photo, photo.caption), tuple(DOG))
		self.cat.assert_not_called()

	async def test_other_text_gets_no_answer(self):
		await self.feed(message("привет"))
		self.assertEqual(self.session.requests, [])
		self.cat.assert_not_called()
		self.dog.assert_not_called()

	async def test_a_sticker_is_not_mistaken_for_text(self):
		# aiogram 3 hands a catch-all handler every message; this one has no text.
		result = await self.feed(message(sticker=True))
		self.assertIs(result, UNHANDLED)
		self.assertEqual(self.session.requests, [])

	async def test_an_upstream_failure_is_answered_not_swallowed(self):
		self.cat.side_effect = aiohttp.ClientConnectionError("down")
		with self.assertLogs(level="ERROR"):
			await self.feed(message("котик"))
		self.assertEqual(self.session.sent("SendPhoto"), [])
		[sent] = self.session.sent("SendMessage")
		self.assertIn("Что-то пошло не так", sent.text)


class InlineTest(HandlerTest):
	async def test_an_inline_query_is_answered_with_a_cat(self):
		update = inline_query("")
		await self.feed(update)
		[answer] = self.session.sent("AnswerInlineQuery")
		self.assertEqual(answer.inline_query_id, update.inline_query.id)
		[result] = answer.results
		self.assertEqual(result.photo_url, CAT[0])
		self.assertEqual(result.thumbnail_url, CAT[0])
		self.assertEqual(result.caption, CAT[1])
		# Telegram wants a result id of 1-64 bytes
		self.assertTrue(1 <= len(result.id.encode()) <= 64)

	async def test_inline_results_get_fresh_ids(self):
		await self.feed(inline_query(""))
		await self.feed(inline_query(""))
		first, second = self.session.sent("AnswerInlineQuery")
		self.assertNotEqual(first.results[0].id, second.results[0].id)

	async def test_a_failed_inline_query_still_gets_an_answer(self):
		# an unanswered inline query leaves the client spinning
		self.cat.side_effect = aiohttp.ClientConnectionError("down")
		with self.assertLogs(level="ERROR"):
			await self.feed(inline_query(""))
		[answer] = self.session.sent("AnswerInlineQuery")
		self.assertEqual(answer.results, [])


if __name__ == "__main__":
	unittest.main()
