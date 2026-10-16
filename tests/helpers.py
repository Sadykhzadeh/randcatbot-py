'''
A Bot that never talks to Telegram, and builders for the updates fed to it.

FakeSession stands in for aiogram's HTTP session: every Bot API call the
handlers make is recorded instead of sent, and answered with a plausible
result, so a test can run the real dispatcher - filters and all - and then
look at exactly what the bot would have sent.
'''

import asyncio
import datetime
import itertools

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Chat, InaccessibleMessage, InlineQuery, Message, Sticker, Update, User

from main import DEFAULTS

BOT_USER = User(id=42, is_bot=True, first_name="randcatbot", username="randcatbot")
USER = User(id=1001, is_bot=False, first_name="Ann", language_code="ru")

_ids = itertools.count(1)


class FakeSession(BaseSession):
	def __init__(self):
		super().__init__()
		self.requests = []
		# seconds a method takes to answer, as sendPhoto does while Telegram
		# downloads the picture; everything else answers at once
		self.delays = {}
		# Bot API methods that fail, mapped to Telegram's error description;
		# one starting "Forbidden" is a 403, as Telegram sends it. A list of
		# descriptions fails that many calls in turn, and the rest succeed.
		self.failures = {}
		# Bot API methods refused by flood control, mapped to the seconds
		# Telegram asks the bot to wait
		self.flood_waits = {}
		# ids of messages deleted before the bot got to answer them
		self.deleted = set()
		# what getMe answers
		self.me = BOT_USER

	async def make_request(self, bot, method, timeout=None):
		self.requests.append(method)
		delay = self.delays.get(type(method).__name__)
		if delay:
			await asyncio.sleep(delay)
		wait = self.flood_waits.get(type(method).__name__)
		if wait:
			raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=wait)
		failure = self.failures.get(type(method).__name__)
		if isinstance(failure, list):
			failure = failure.pop(0) if failure else None
		if failure:
			error = TelegramForbiddenError if failure.startswith("Forbidden") else TelegramBadRequest
			raise error(method=method, message=failure)
		reply = getattr(method, "reply_parameters", None)
		if reply is not None and reply.message_id in self.deleted:
			# resolved the way the real session does, bot defaults included
			if not self.prepare_value(reply, bot, {}, _dumps_json=False).get("allow_sending_without_reply"):
				raise TelegramBadRequest(method=method, message="Bad Request: message to be replied not found")
		returning = method.__returning__
		if returning is bool:
			return True
		if returning is User:
			return self.me
		if returning is Message:
			return Message(
				message_id=next(_ids),
				date=datetime.datetime.now(datetime.timezone.utc),
				chat=Chat(id=getattr(method, "chat_id", 1), type="private"),
				from_user=BOT_USER,
			)
		return None

	async def stream_content(self, *args, **kwargs):
		raise NotImplementedError
		yield b""

	async def close(self):
		pass

	def sent(self, name):
		'''The recorded calls of one Bot API method, e.g. sent("SendPhoto").'''
		return [m for m in self.requests if type(m).__name__ == name]


def make_bot():
	session = FakeSession()
	return Bot("42:TEST", session=session, default=DEFAULTS), session


def message(text=None, *, user=USER, chat_type="private", sticker=False):
	chat_id = user.id if chat_type == "private" else -100500
	extra = {}
	if sticker:
		extra["sticker"] = Sticker(
			file_id="s", file_unique_id="s", type="regular",
			width=512, height=512, is_animated=False, is_video=False,
		)
	return Update(update_id=next(_ids), message=Message(
		message_id=next(_ids),
		date=datetime.datetime.now(datetime.timezone.utc),
		chat=Chat(id=chat_id, type=chat_type),
		from_user=user,
		text=text,
		**extra,
	))


def inline_query(query="", *, user=USER):
	return Update(update_id=next(_ids), inline_query=InlineQuery(
		id=str(next(_ids)), from_user=user, query=query, offset="",
	))


def button(data, *, user=USER, chat_type="private", inaccessible=False):
	'''A press on a button under a message the bot sent earlier.'''
	chat = Chat(id=user.id if chat_type == "private" else -100500, type=chat_type)
	if inaccessible:
		msg = InaccessibleMessage(chat=chat, message_id=next(_ids))
	else:
		msg = Message(
			message_id=next(_ids),
			date=datetime.datetime.now(datetime.timezone.utc),
			chat=chat,
			from_user=BOT_USER,
		)
	return Update(update_id=next(_ids), callback_query=CallbackQuery(
		id=str(next(_ids)), from_user=user, chat_instance="1", data=data, message=msg,
	))


def reply_target(method):
	'''The message id a sent message replies to, or None.'''
	params = getattr(method, "reply_parameters", None)
	if params is not None:
		return params.message_id
	return getattr(method, "reply_to_message_id", None)
