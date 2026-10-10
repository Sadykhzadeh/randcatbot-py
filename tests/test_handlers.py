'''
The handlers, run through the real dispatcher against a bot that records what
it would have sent. No token and no network: the animal APIs are mocked out.
'''

import logging
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction, ParseMode

import animals
import main
from animals import Unavailable
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


class MenuTest(HandlerTest):
	async def test_cat_sends_a_cat(self):
		await self.feed(message("/cat"))
		[photo] = self.session.sent("SendPhoto")
		self.assertEqual((photo.photo, photo.caption), tuple(CAT))

	async def test_dog_works_in_a_group_when_addressed_to_this_bot(self):
		# privacy mode shows a bot commands in a group, never plain words
		await self.feed(message("/dog@randcatbot", chat_type="supergroup"))
		[photo] = self.session.sent("SendPhoto")
		self.assertEqual((photo.photo, photo.caption), tuple(DOG))

	async def test_the_menu_is_set_on_startup(self):
		with patch.object(animals, "cats"), patch.object(animals, "dogs"):
			await main.dp.emit_startup(bot=self.bot)
		[sent] = self.session.sent("SetMyCommands")
		self.assertEqual([c.command for c in sent.commands], ["cat", "dog", "help"])
		self.assertTrue(all(c.description for c in sent.commands))

	async def test_every_command_in_the_menu_is_answered(self):
		for command in main.COMMANDS:
			await self.feed(message("/" + command.command))
		answers = self.session.sent("SendPhoto") + self.session.sent("SendMessage")
		self.assertEqual(len(answers), len(main.COMMANDS))

	async def test_a_menu_telegram_refuses_does_not_stop_the_bot(self):
		self.session.failures["SetMyCommands"] = "Bad Request: BOT_COMMAND_INVALID"
		with self.assertLogs(level="WARNING"):
			await main.set_commands(self.bot)


class KeywordTest(HandlerTest):
	async def test_kotik_replies_with_a_cat_photo(self):
		update = message("котик")
		await self.feed(update)
		[photo] = self.session.sent("SendPhoto")
		self.assertEqual((photo.photo, photo.caption), tuple(CAT))
		self.assertEqual(photo.chat_id, update.message.chat.id)
		self.assertEqual(reply_target(photo), update.message.message_id)
		self.dog.assert_not_called()

	async def test_the_upload_status_goes_out_alongside_the_photo_not_before_it(self):
		# Awaiting sendChatAction first held every photo back by a round trip.
		self.session.delays["SendPhoto"] = 0.05
		await self.feed(message("котик"))
		order = [type(m).__name__ for m in self.session.requests]
		self.assertEqual(order, ["SendPhoto", "SendChatAction"])
		[action] = self.session.sent("SendChatAction")
		self.assertEqual(action.action, ChatAction.UPLOAD_PHOTO)

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

	async def test_with_every_cat_source_down_the_reply_says_so(self):
		self.cat.side_effect = Unavailable("_thecatapi, _cataas")
		with self.assertLogs(level="WARNING"):
			await self.feed(message("котик"))
		self.assertEqual(self.session.sent("SendPhoto"), [])
		[sent] = self.session.sent("SendMessage")
		self.assertIn("Котики сейчас недоступны", sent.text)
		self.assertIn("через минуту", sent.text)

	async def test_with_every_dog_source_down_the_reply_says_so(self):
		self.dog.side_effect = Unavailable("_dogceo, _randomdog")
		with self.assertLogs(level="WARNING"):
			await self.feed(message("собачка"))
		[sent] = self.session.sent("SendMessage")
		self.assertIn("Собачки сейчас недоступны", sent.text)

	async def test_a_photo_telegram_cannot_fetch_gets_an_apology(self):
		self.session.failures["SendPhoto"] = "Bad Request: failed to get HTTP URL content"
		with self.assertLogs(level="ERROR"):
			await self.feed(message("котик"))
		[sent] = self.session.sent("SendMessage")
		self.assertIn("Что-то пошло не так", sent.text)


class InlineTest(HandlerTest):
	async def answer(self, query):
		update = inline_query(query)
		await self.feed(update)
		[answer] = self.session.sent("AnswerInlineQuery")
		self.assertEqual(answer.inline_query_id, update.inline_query.id)
		return answer.results

	async def test_an_empty_query_offers_cats_and_dogs(self):
		results = await self.answer("")
		self.assertEqual([r.photo_url for r in results], [CAT[0], DOG[0]] * 2)
		self.assertEqual([r.title for r in results], ["😺", "🐶"] * 2)
		cat = results[0]
		self.assertEqual(cat.thumbnail_url, CAT[0])
		self.assertEqual(cat.caption, CAT[1])

	async def test_a_query_about_cats_offers_only_cats(self):
		results = await self.answer("Котики")
		self.assertEqual([r.photo_url for r in results], [CAT[0]] * 4)
		self.dog.assert_not_called()

	async def test_a_query_about_dogs_offers_only_dogs(self):
		for query in ("собака", "пёсик", "dog"):
			self.session.requests.clear()
			results = await self.answer(query)
			self.assertEqual([r.photo_url for r in results], [DOG[0]] * 4, query)
		self.cat.assert_not_called()

	async def test_a_query_about_both_offers_both(self):
		results = await self.answer("кот и собака")
		self.assertEqual({r.photo_url for r in results}, {CAT[0], DOG[0]})

	async def test_every_result_gets_its_own_valid_id(self):
		ids = [r.id for r in await self.answer("")]
		self.assertEqual(len(set(ids)), len(ids))
		# Telegram wants a result id of 1-64 bytes
		self.assertTrue(all(1 <= len(i.encode()) <= 64 for i in ids))

	async def test_with_the_dog_sources_down_the_cats_still_come(self):
		self.dog.side_effect = Unavailable("_dogceo, _randomdog")
		with self.assertLogs(level="WARNING"):
			results = await self.answer("")
		self.assertEqual([r.photo_url for r in results], [CAT[0]] * 2)

	async def test_with_everything_down_the_query_still_gets_an_answer(self):
		# an unanswered inline query leaves the client spinning
		self.cat.side_effect = Unavailable("_thecatapi, _cataas")
		self.dog.side_effect = RuntimeError("bug")
		with self.assertLogs(level="WARNING") as logs:
			results = await self.answer("")
		self.assertEqual(results, [])
		self.assertTrue(any(r.levelno == logging.ERROR and r.exc_info for r in logs.records))


if __name__ == "__main__":
	unittest.main()
