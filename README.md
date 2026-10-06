# Telegram Bot "Котики и не только" ("Cats & not only")
[@randcatbot](https://t.me/randcatbot) is a [Telegram](https://telegram.org) bot, written thanks to the [Telegram Bot Api](https://core.telegram.org/bots/api) and the [Python Aiogram framework](https://github.com/aiogram/aiogram). More information about this bot (in Russian) you can read [here](https://telegra.ph/O-Telegram-bote-randcatbot-04-22).

License: MIT

*The code has NOT been polished and is provided "as is". There's a lot of code that is redundant and there are tons of improvements that can be made.*

# Running it

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=...        # from @BotFather; see .env.example
python main.py
```

Needs **Python 3.8 - 3.11**: aiogram 2.x requires `aiohttp>=3.8,<3.9`, and
that has no wheels for newer interpreters. Moving to aiogram 3 is what lifts
the ceiling.

`BOT_TOKEN` is read from the environment and the bot refuses to start without
it.

# FAQ

Q: Where exactly does the bot take photos from?

A: The bot takes photos of cats from [CatAPI](https://thecatapi.com).

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
