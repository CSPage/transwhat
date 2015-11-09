__author__ = "Steffen Vogel"
__copyright__ = "Copyright 2013, Steffen Vogel"
__license__ = "GPLv3"
__maintainer__ = "Steffen Vogel"
__email__ = "post@steffenvogel.de"
__status__ = "Prototype"

"""
 This file is part of transWhat

 transWhat is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 any later version.

 transwhat is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with transWhat. If not, see <http://www.gnu.org/licenses/>.
"""

from Spectrum2 import protocol_pb2

import logging
import threading


class Number():

	def __init__(self, number, state, db):
		self.number = number
		self.db = db
		self.state = state

		cur = self.db.cursor()
		cur.execute("SELECT id FROM numbers WHERE number = %s AND state = %s", (self.number, self.state))
		if (cur.rowcount):
			self.id = cur.fetchone()[0]
		else:
			cur.execute("REPLACE numbers (number, state) VALUES (%s, %s)", (self.number, self.state))
			self.db.commit()
			self.id = cur.lastrowid

	def __str__(self):
		return "%s (id=%s)" % (self.number, self.id)


class Buddy():
	def __init__(self, owner, number, nick, groups, image_hash, id, db):
		self.id = id
		self.db = db

		self.nick = nick
		self.owner = owner
		self.number = number
		self.groups = groups
		self.image_hash = image_hash
		self.statusMsg = ""


	def update(self, nick, groups, image_hash):
		self.nick = nick
		self.groups = groups
		if image_hash is not None:
			self.image_hash = image_hash

		groups = u",".join(groups).encode("latin-1")
		cur = self.db.cursor()
		cur.execute("UPDATE buddies SET nick = %s, groups = %s, image_hash = %s WHERE owner_id = %s AND buddy_id = %s", (self.nick, groups, self.image_hash, self.owner.id, self.number.id))
		self.db.commit()

	def delete(self):
		cur = self.db.cursor()
		cur.execute("DELETE FROM buddies WHERE owner_id = %s AND buddy_id = %s", (self.owner.id, self.number.id))
		self.db.commit()
		self.id = None

	@staticmethod
	def create(owner, number, nick, groups, image_hash, db):
		groups = u",".join(groups).encode("latin-1")
		cur = db.cursor()
		cur.execute("REPLACE buddies (owner_id, buddy_id, nick, groups, image_hash) VALUES (%s, %s, %s, %s, %s)", (owner.id, number.id, nick, groups, image_hash))
		db.commit()

		return Buddy(owner, number, nick, groups, image_hash, cur.lastrowid, db)

	def __str__(self):
		return "%s (nick=%s, id=%s)" % (self.number, self.nick, self.id)

class BuddyList(dict):

	def __init__(self, owner, db):
		self.db = db
		self.owner = Number(owner, 1, db)
		self.lock = threading.Lock()


	def load(self):
		self.clear()
		self.lock.acquire()

		cur = self.db.cursor()
		cur.execute("""SELECT
					b.id AS id,
					n.number AS number,
					b.nick AS nick,
					b.groups AS groups,
					n.state AS state,
					b.image_hash AS image_hash
				FROM buddies AS b
				LEFT JOIN numbers AS n
					ON b.buddy_id = n.id
				WHERE
					b.owner_id IN (%s, 0)
					AND n.state >= 1
				ORDER BY b.owner_id DESC""", self.owner.id)

		for i in range(cur.rowcount):
			id, number, nick, groups, state, image_hash = cur.fetchone()
			self[number] = Buddy(self.owner, Number(number, state, self.db), nick.decode('latin1'), groups.split(","), image_hash, id, self.db)
		self.lock.release()


	def update(self, number, nick, groups, image_hash):
		self.lock.acquire()
		if number in self:
			buddy = self[number]
			buddy.update(nick, groups, image_hash)
		else:
			buddy = self.add(number, nick, groups, 1, image_hash)
		self.lock.release()

		return buddy

	def add(self, number, nick, groups = [], state = 0, image_hash = ""):
		return Buddy.create(self.owner, Number(number, state, self.db), nick, groups, image_hash, self.db)

	def remove(self, number):
		try:
			buddy = self[number]
			self.lock.acquire()
			buddy.delete()
			self.lock.release()
			return buddy
		except KeyError:
			return None

	def prune(self):
		self.lock.acquire()

		cur = self.db.cursor()
		cur.execute("DELETE FROM buddies WHERE owner_id = %s", self.owner.id)
		self.db.commit()
		self.lock.release()


	def sync(self, user, password):
		self.lock.acquire()
		cur = self.db.cursor()
		cur.execute("""SELECT
					n.number AS number,
					n.state AS state
				FROM buddies AS r 
				LEFT JOIN numbers AS n
					ON r.buddy_id = n.id
				WHERE
					r.owner_id = %s""", self.owner.id)

		# prefix every number with leading 0 to force internation format
		numbers = dict([("+" + number, state) for number, state in cur.fetchall()])

		if len(numbers) == 0:
			return 0

		result = WAContactsSyncRequest(user, password, numbers.keys()).send()

		using = 0
		for number in result['c']:
			cur = self.db.cursor()
			cur.execute("UPDATE numbers SET state = %s WHERE number = %s", (number['w'], number['n']))
			self.db.commit()
			using += number['w']
		self.lock.release()
		return using
