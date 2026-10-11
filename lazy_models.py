# -*- coding: utf-8 -*-

'''
Import aiogram without paying for the whole Bot API up front.

The end of aiogram/types/__init__.py calls model_rebuild() on every one of its
~400 pydantic models. Each model is declared with defer_build=True, so pydantic
would build a schema only for the ones that are used, but the loop builds them
all: about a second of start-up and ~100 MiB of resident memory, for a bot
that touches a dozen of those types.

Importing this module before aiogram turns the loop into a no-op and puts the
names the forward references need into each model's own module, so pydantic
can build a model's schema on first use instead. The bot is the same; it just
starts about three times faster and idles in less than half the memory.

If aiogram has already been imported, or a future release stops doing the
eager rebuild, there is nothing to skip and this does nothing.
'''

import sys

if 'aiogram.types' not in sys.modules:
	from pydantic import BaseModel

	_rebuild = BaseModel.__dict__['model_rebuild']
	BaseModel.model_rebuild = classmethod(lambda cls, *args, **kwargs: None)
	try:
		import aiogram.types as _types
	finally:
		BaseModel.model_rebuild = _rebuild

	from typing import Literal, Optional, Union

	from aiogram.client.default import Default

	# What aiogram hands model_rebuild() as the namespace for its forward refs.
	_names = {name: getattr(_types, name) for name in _types.__all__}
	_names.update(List=list, Optional=Optional, Union=Union, Literal=Literal, Default=Default)
	_modules = {getattr(getattr(_types, name), '__module__', None) for name in _types.__all__}
	for _module in map(sys.modules.get, _modules - {None}):
		if _module is not None:
			for _key, _value in _names.items():
				_module.__dict__.setdefault(_key, _value)
