# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import time

ALLOW, WARN, DROP = "allow", "warn", "drop"


class Throttle:
	'''
	At most one request per `interval` seconds per key.

	The first request refused in a window is answered with WARN, so the person
	learns why nothing came; any more in the same window get DROP and no
	answer at all, or the refusals would become the flood themselves.
	'''

	# Past this many keys, the ones whose window is over are forgotten.
	PRUNE_AT = 10_000

	def __init__(self, interval, clock=time.monotonic):
		self.interval = interval
		self._clock = clock
		self._until = {}
		self._warned = set()

	def hit(self, key):
		now = self._clock()
		if now >= self._until.get(key, 0):
			if len(self._until) >= self.PRUNE_AT:
				self._prune(now)
			self._until[key] = now + self.interval
			self._warned.discard(key)
			return ALLOW
		if key in self._warned:
			return DROP
		self._warned.add(key)
		return WARN

	def _prune(self, now):
		self._until = {k: t for k, t in self._until.items() if t > now}
		self._warned &= self._until.keys()
