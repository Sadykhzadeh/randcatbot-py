# Telegram Bot "Котики и не только" ("Cats & not only")
[@randcatbot](https://t.me/randcatbot) is a [Telegram](https://telegram.org) bot, written thanks to the [Telegram Bot Api](https://core.telegram.org/bots/api) and the [Python Aiogram framework](https://github.com/aiogram/aiogram). More information about this bot (in Russian) you can read [here](https://telegra.ph/O-Telegram-bote-randcatbot-04-22).

License: MIT

*The code has NOT been polished and is provided "as is". There's a lot of code that is redundant and there are tons of improvements that can be made.*

# Using it

- **котик** or **собачка** in a private chat, or **/cat** and **/dog**
  anywhere: a random picture. In groups only the commands work, because a
  bot in Telegram's default privacy mode is not shown plain messages there.
- **/help**: how to use the bot. The commands are also in the menu next to
  the input field; the bot sets it on every start.

# Running it

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=...        # from @BotFather; see .env.example
python main.py
```

Needs **Python 3.10 - 3.14**, the range aiogram 3 supports.

`BOT_TOKEN` is read from the environment and the bot refuses to start without
it.

## Tests

```sh
python -m unittest -v
```

They need neither a token nor the network. The handlers run through the real
dispatcher against a bot whose HTTP session records every Bot API call
instead of sending it (`tests/helpers.py`), and the animal APIs are mocked.

# FAQ

Q: Where exactly does the bot take photos from?

A: Cats come from [TheCatAPI](https://thecatapi.com) and dogs from
[Dog CEO](https://dog.ceo/dog-api/). When one of them is down, the bot falls
back to [Cat as a Service](https://cataas.com) or [random.dog](https://random.dog)
on its own. Pictures are fetched ten at a time and kept ready, so a request
does not wait on any of these APIs.

Q: Why are there no dogs in inline mode?

A: This is all under development, so far the inline mode is only able to send a random cat.

Q: Is the author obsessed with cats?

A: No... At least I want to believe it....

# Screenshots
![Screenshot of cat](https://github.com/Sadykhzadeh/randcatbot-py/blob/master/screenshots/Hello_Cat.png)
![Screenshot of inline cat](https://github.com/Sadykhzadeh/randcatbot-py/blob/master/screenshots/Hello_Inline_Cat.png)
![Screenshot of dog](https://github.com/Sadykhzadeh/randcatbot-py/blob/master/screenshots/Hello_Dog.png)

## Author
(C) 2020 by [Azer Sadykhzadeh](https://sadykhzadeh.github.io).
