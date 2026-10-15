'''
The handlers, run through the real dispatcher against a bot that records what
it would have sent. No token and no network: the animal APIs are mocked out.
'''

import itertools
import logging
import unittest
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction, ParseMode

import animals
import main
from animals import Unavailable
from config import help_text, start_text
from tests.helpers import FakeSession, USER, inline_query, make_bot, message, reply_target
from throttle import Throttle

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
		# A fresh limiter whose clock jumps ten seconds on every look, so tests
		# that are not about the rate limit never run into it.
		ticks = itertools.count(0, 10)
		patcher = patch.object(main, "limiter", Throttle(1.0, clock=lambda: next(ticks)))
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


class MainTest(unittest.IsolatedAsyncioTestCase):
	# The handler tests build their own Bot; this checks the one main() makes.
	async def test_main_starts_the_bot_the_way_the_handlers_are_tested(self):
		bots = []
		def make(**kwargs):
			bots.append(Bot(session=FakeSession(), **kwargs))
			return bots[-1]
		with patch.object(main, "token", "42:TEST"), patch.object(main, "Bot", make), \
				patch.object(main.dp, "start_polling", AsyncMock()) as polling:
			await main.main()
		[bot] = bots
		self.assertTrue(bot.default.allow_sending_without_reply)
		[delete] = bot.session.sent("DeleteWebhook")
		self.assertTrue(delete.drop_pending_updates)
		polling.assert_awaited_once_with(bot)

	async def test_main_refuses_to_start_without_a_token(self):
		with patch.object(main, "token", ""), patch.object(main, "Bot") as bot:
			with self.assertRaises(SystemExit):
				await main.main()
		bot.assert_not_called()


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

	async def test_a_message_deleted_before_the_answer_still_gets_one(self):
		# as in a group whose admin bot deletes every command on arrival
		for text in ("/cat", "/help"):
			update = message(text, chat_type="supergroup")
			self.session.deleted.add(update.message.message_id)
			await self.feed(update)
		self.assertEqual(len(self.session.sent("SendPhoto")), 1)
		[sent] = self.session.sent("SendMessage")
		self.assertEqual(sent.text, help_text)

	async def test_under_flood_control_nothing_more_is_sent_into_the_chat(self):
		# Telegram refuses everything into the chat until the wait is over,
		# so an apology would only be refused as well
		self.session.flood_waits.update(SendPhoto=30, SendMessage=30)
		with self.assertLogs(level="WARNING") as logs:
			await self.feed(message("котик", chat_type="supergroup"))
		self.assertEqual(len(self.session.sent("SendPhoto")), 1)
		self.assertEqual(self.session.sent("SendMessage"), [])
		self.assertTrue(all(r.levelno == logging.WARNING for r in logs.records))

	async def test_a_refused_upload_status_is_not_logged_as_an_error(self):
		# Telegram limits sendChatAction too, and the status goes out from a
		# task nobody awaits
		self.session.delays["SendPhoto"] = 0.05
		self.session.flood_waits["SendChatAction"] = 30
		with self.assertNoLogs(level="ERROR"):
			await self.feed(message("котик", chat_type="supergroup"))
		self.assertEqual(len(self.session.sent("SendChatAction")), 1)
		self.assertEqual(len(self.session.sent("SendPhoto")), 1)

	async def test_a_group_that_forbids_photos_is_told_so(self):
		# a group whose members may not send media, and the bot is a member
		self.session.failures["SendPhoto"] = "Bad Request: not enough rights to send photos to the chat"
		with self.assertLogs(level="WARNING") as logs:
			await self.feed(message("/cat", chat_type="supergroup"))
		[sent] = self.session.sent("SendMessage")
		self.assertIn("нельзя отправлять фото", sent.text)
		self.assertTrue(all(r.levelno == logging.WARNING and not r.exc_info for r in logs.records))

	async def test_a_bot_muted_in_a_group_logs_one_line_per_refusal(self):
		# the admins took away the right to send anything; commands still
		# reach the bot, but its answers, the apology too, are all refused
		self.session.failures.update(
			SendPhoto="Bad Request: not enough rights to send photos to the chat",
			SendMessage="Bad Request: not enough rights to send text messages to the chat",
		)
		with self.assertLogs(level="WARNING") as logs:
			await self.feed(message("/cat", chat_type="supergroup"))
			await self.feed(message("/help", chat_type="supergroup"))
		self.assertEqual(len(self.session.sent("SendMessage")), 2)
		self.assertTrue(all(r.levelno == logging.WARNING and not r.exc_info for r in logs.records))

	async def test_a_bot_removed_before_the_photo_went_out_tries_nothing_more(self):
		self.session.failures["SendPhoto"] = "Forbidden: bot was kicked from the supergroup chat"
		with self.assertLogs(level="WARNING") as logs:
			await self.feed(message("/dog", chat_type="supergroup"))
		self.assertEqual(self.session.sent("SendMessage"), [])
		[record] = logs.records
		self.assertEqual(record.levelno, logging.WARNING)
		self.assertIn("kicked", record.getMessage())

	async def test_a_photo_telegram_cannot_fetch_gets_an_apology(self):
		self.session.failures["SendPhoto"] = "Bad Request: failed to get HTTP URL content"
		with self.assertLogs(level="ERROR"):
			await self.feed(message("котик"))
		[sent] = self.session.sent("SendMessage")
		self.assertIn("Что-то пошло не так", sent.text)


class RateLimitTest(HandlerTest):
	def setUp(self):
		super().setUp()
		self.now = 0.0
		patcher = patch.object(main, "limiter", Throttle(1.0, clock=lambda: self.now))
		patcher.start()
		self.addCleanup(patcher.stop)

	async def test_a_burst_gets_one_picture_and_one_explanation(self):
		for text in ("/cat", "котик", "/dog", "/cat"):
			await self.feed(message(text))
		self.assertEqual(len(self.session.sent("SendPhoto")), 1)
		[sent] = self.session.sent("SendMessage")
		self.assertIn("Не так быстро", sent.text)
		# nothing was fetched for the refused ones
		self.assertEqual(self.cat.await_count + self.dog.await_count, 1)

	async def test_under_flood_control_no_reply_ends_in_a_traceback(self):
		# the chat is over its limit: the "slow down", /help and the
		# inline answer are refused just like a photo
		self.session.flood_waits.update(SendPhoto=30, SendMessage=30, AnswerInlineQuery=5)
		with self.assertLogs(level="WARNING") as logs:
			for update in (message("/cat"), message("/cat"), message("/help"), inline_query("")):
				await self.feed(update)
		self.assertEqual(len(self.session.sent("SendMessage")), 2)
		self.assertEqual(len(self.session.sent("AnswerInlineQuery")), 1)
		self.assertEqual(len(logs.records), 4)
		self.assertTrue(all(r.levelno == logging.WARNING and not r.exc_info for r in logs.records))

	async def test_a_second_later_the_next_picture_comes(self):
		await self.feed(message("/cat"))
		self.now += 1
		await self.feed(message("/dog"))
		self.assertEqual(len(self.session.sent("SendPhoto")), 2)
		self.assertEqual(self.session.sent("SendMessage"), [])

	async def test_people_in_one_group_do_not_slow_each_other_down(self):
		bob = USER.model_copy(update={"id": 1002, "first_name": "Bob"})
		await self.feed(message("/cat", chat_type="supergroup"))
		await self.feed(message("/cat", user=bob, chat_type="supergroup"))
		self.assertEqual(len(self.session.sent("SendPhoto")), 2)

	async def test_other_commands_and_inline_mode_are_not_limited(self):
		await self.feed(message("/cat"))
		await self.feed(message("/help"))
		await self.feed(inline_query(""))
		[sent] = self.session.sent("SendMessage")
		self.assertEqual(sent.text, help_text)
		[answer] = self.session.sent("AnswerInlineQuery")
		self.assertEqual(len(answer.results), 4)


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
