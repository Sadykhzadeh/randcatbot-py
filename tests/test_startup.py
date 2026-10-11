# -*- coding: utf-8 -*-

'''
lazy_models.py skips aiogram's eager schema build. These tests run in a fresh
interpreter, because the effect only exists if aiogram was not imported yet.
'''

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every model has to be able to build itself, or a forward reference that
# lazy_models.py failed to provide would only show up in production, on the
# first update that happens to use that type.
BUILD_EVERYTHING = '''
import main
import aiogram.methods as methods
import aiogram.types as types
from pydantic import BaseModel

assert not types.Message.__pydantic_complete__, "schemas were built at import"

built = 0
for module in (types, methods):
	for name in module.__all__:
		cls = getattr(module, name)
		if isinstance(cls, type) and issubclass(cls, BaseModel):
			cls.model_rebuild(raise_errors=True)
			assert cls.__pydantic_complete__, name
			built += 1
print(built)
'''

PARSE_UPDATE = '''
import main
from aiogram.types import Update

update = Update.model_validate({
	"update_id": 1,
	"message": {
		"message_id": 7, "date": 1, "text": "котик",
		"chat": {"id": 5, "type": "private"},
		"from": {"id": 5, "is_bot": False, "first_name": "A"},
		"reply_to_message": {"message_id": 6, "date": 1, "chat": {"id": 5, "type": "private"}},
	},
})
assert update.message.text == "котик"
assert update.message.reply_to_message.message_id == 6
'''


def run(code):
	return subprocess.run(
		[sys.executable, '-c', code],
		cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120,
	)


class LazyModelsTest(unittest.TestCase):
	def test_every_model_builds_on_demand(self):
		done = run(BUILD_EVERYTHING)
		self.assertEqual(done.returncode, 0, done.stderr)
		self.assertGreater(int(done.stdout.strip()), 300)

	def test_an_update_parses_without_the_eager_build(self):
		done = run(PARSE_UPDATE)
		self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == '__main__':
	unittest.main()
