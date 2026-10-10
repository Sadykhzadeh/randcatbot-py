import unittest

from throttle import ALLOW, DROP, WARN, Throttle


class ThrottleTest(unittest.TestCase):
	def setUp(self):
		self.now = 100.0
		self.throttle = Throttle(1.0, clock=lambda: self.now)

	def test_one_request_per_interval(self):
		self.assertEqual(self.throttle.hit("ann"), ALLOW)
		self.now += 0.5
		self.assertEqual(self.throttle.hit("ann"), WARN)
		self.now += 0.5
		self.assertEqual(self.throttle.hit("ann"), ALLOW)

	def test_only_the_first_refusal_in_a_window_is_answered(self):
		self.throttle.hit("ann")
		self.assertEqual(self.throttle.hit("ann"), WARN)
		self.assertEqual(self.throttle.hit("ann"), DROP)
		self.assertEqual(self.throttle.hit("ann"), DROP)
		self.now += 1
		self.assertEqual(self.throttle.hit("ann"), ALLOW)
		# a new window, so a new refusal is explained again
		self.assertEqual(self.throttle.hit("ann"), WARN)

	def test_keys_do_not_share_a_window(self):
		self.assertEqual(self.throttle.hit("ann"), ALLOW)
		self.assertEqual(self.throttle.hit("bob"), ALLOW)
		self.assertEqual(self.throttle.hit("ann"), WARN)

	def test_expired_keys_are_forgotten_once_there_are_many(self):
		self.throttle.PRUNE_AT = 3
		for key in ("a", "b", "c"):
			self.throttle.hit(key)
		self.throttle.hit("c")  # warned, and still inside its window
		self.now += 2
		self.throttle.hit("d")  # every window but d's is over: pruned
		self.assertEqual(set(self.throttle._until), {"d"})
		self.assertEqual(self.throttle._warned, set())

	def test_keys_still_inside_their_window_survive_a_prune(self):
		self.throttle.PRUNE_AT = 2
		self.throttle.hit("a")
		self.now += 2
		self.throttle.hit("b")
		self.throttle.hit("c")  # prunes a, keeps b
		self.assertEqual(set(self.throttle._until), {"b", "c"})
		self.assertEqual(self.throttle.hit("b"), WARN)


if __name__ == "__main__":
	unittest.main()
