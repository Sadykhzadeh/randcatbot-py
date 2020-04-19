# -*- coding: utf-8 -*-

'''
Code of @randcatbot [https://t.me/randcatbot] by Azer Sadykhzadeh

Telegram: @Sadykhzadeh [https://t.me/Sadykhzadeh]
Github: https://github.com/sadykhzadeh
'''

import requests
import random
from config import cap_mas, dog_mas

class Animals():
	def give_me_a_cat():
		caption = cap_mas[int(random.uniform(0, len(cap_mas)))]
		json = requests.get("https://api.thecatapi.com/v1/images/search").json()
		cat = json[0]['url']
		return [cat, caption]
	def give_me_a_dog():
		caption = dog_mas[int(random.uniform(0, len(dog_mas)))]
		json = requests.get("https://dog.ceo/api/breeds/image/random").json()
		dog = json['message']
		return [dog, caption]