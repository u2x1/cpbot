import json
from datetime import datetime, timedelta, timezone
import sqlite3
import requests
import math
import re

from flask import request, Flask

class CF:
  @staticmethod
  def get(loc, param={}):
    cfhost = 'https://codeforces.com/api'
    return requests.get(url=cfhost+loc, params=param).json()['result']

  @staticmethod
  def userRating(handle):
    return CF.get('/user.info', {'handles': handle})[0]['rating']

  @staticmethod
  def allProblems():
    return CF.get('/problemset.problems')['problems']

  @staticmethod
  def checkAC(handle: str, cid: int, pidx: str):
    ret = CF.get('/user.status', {'handle': handle, 'count': 10})
    ret = list(filter(lambda x:
                      x['verdict'] == "OK"
                      and x['contestId'] == cid
                      and x['problem']['index'] == pidx, ret))
    if len(ret) == 0:
      return None
    return ret[-1]['creationTimeSeconds']
    # r = map(lambda x: x['contestId']



class DbConn:

  @staticmethod
  def dict_factory(cursor, row):
   d = {}
   for idx, col in enumerate(cursor.description):
     d[col[0]] = row[idx]
   return d

  def __init__(self):
    self.conn = sqlite3.connect('data.db')
    self.conn.row_factory = DbConn.dict_factory

  def initDB(self):
    self.createProblemTable()
    self.createDuelTable()
    self.createUserTable()
    self.createEventTable()
    self.updateProblemCache()

  def _dropEveryThing(self):
    self._execute('DROP TABLE `duel`')
    self._execute('DROP TABLE `user`')
    self._execute('DROP TABLE `problem`')
    self._execute('DROP TABLE `event`')

  def updateProblemCache(self):
    @staticmethod
    def _squish_tags(p):
      return (p.get('contestId'), p.get('problemsetName'), p.get('index'), p.get('name'),
              p.get('type'), p.get('points'), p.get('rating'), json.dumps(p.get('tags')))
    query = ('INSERT OR REPLACE INTO problem '
             '(contest_id, problemset_name, [index], name, type, points, rating, tags) '
             'VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
    self.conn.executemany(query, list(map(_squish_tags, CF.allProblems())))
    self.conn.commit()

  def _execute(self, query, param=()):
    ret = self.conn.execute(query, param)
    self.conn.commit()
    return ret

  def createProblemTable(self):
    self._execute(
      'CREATE TABLE IF NOT EXISTS problem ('
      'contest_id       INTEGER,'
      'problemset_name  TEXT,'
      '[index]          TEXT,'
      'name             TEXT NOT NULL,'
      'type             TEXT,'
      'points           REAL,'
      'rating           INTEGER,'
      'tags             TEXT,'
      'PRIMARY KEY (name)'
      ')'
    )

  def createUserTable(self):
    self._execute(
      'CREATE TABLE IF NOT EXISTS user ('
      'qid          INTEGER PRIMARY KEY, '
      'cfhandle     TEXT, '
      'rating       INTEGER, '
      'in_duel_id   INTEGER '
      ')'
    )

  def createEventTable(self):
    self._execute(
      'CREATE TABLE IF NOT EXISTS event ('
      'event_id      INTEGER PRIMARY KEY, '
      'qid           INTEGER, '
      'status        INTEGER'
      ')'
    )

  def createDuelTable(self):
    self._execute(
      'CREATE TABLE IF NOT EXISTS duel ('
      'duel_id       INTEGER PRIMARY KEY, '
      'p_contest_id  INTEGER, '
      'p_index       INTEGER, '
      'p_difficulty  INTEGER, '
      'player1       INTEGER, '
      'player2       INTEGER, '
      'winner        TEXT, '
      'status        INTEGER DEFAULT 0, '
      "duel_time     TIMESTAMP DEFAULT (strftime('%s','now'))"
      ')'
    )
  
  # 0:attend_duel 1:win_duel 2:skip_duel
  def createEvent(self, qid: int, status: int):
    query = ('INSERT INTO event '
             '(qid, status) '
             'VALUES (?, ?)')
    self._execute(query, (qid, status))

  def getEventCount(self, qid: int, status: int):
    return self._execute(f'SELECT COUNT(*) FROM `event` WHERE `qid`={qid} AND `status`={status}').fetchone()['COUNT(*)']

  def createUser(self, qid: int, cfhandle: str, rating: int):
    query = ('INSERT OR REPLACE INTO user '
             '(qid, cfhandle, rating) '
             'VALUES (?, ?, ?)')
    self._execute(query, (qid, cfhandle, rating))
  
  def createDuel(self, cid: int, pidx: str, pdfc: int, p1: int, p2: int):
    query = ('INSERT INTO `duel` '
             '(p_contest_id, p_index, p_difficulty, player1, player2)'
             'VALUES (?, ?, ?, ?, ?)')
    return self._execute(query, (cid, pidx, pdfc, p1, p2)).lastrowid

  def getInvitedDuel(self, qid: int):
    return self._execute(f'SELECT * FROM `duel` WHERE `status`=0 AND `player2`={qid}').fetchone()

  def setDuelWinner(self, duel_id: int, winner: int):
    self._execute(f'UPDATE `duel` SET `winner`={winner} WHERE `duel_id`={duel_id}')

  def putInDuel(self, qid: int, duel_id: int):
    self._execute(f'UPDATE `user` SET `in_duel_id`={duel_id} WHERE `qid`={qid}')

  def clearDuelStatus(self, qid: int):
    self._execute(f'UPDATE `user` SET `in_duel_id`=NULL WHERE `qid`={qid}')

  def addRating(self, qid: int, delta: int):
    self._execute(f'UPDATE `user` SET rating=rating+{delta} WHERE `qid`={qid}')

  def getDuelTime(self, duel_id: int):
    return self._execute(f'SELECT duel_time FROM `duel` WHERE `duel_id`={duel_id}').fetchone()

  def getDuelId(self, qid: int):
    return self.getUser(qid)['in_duel_id']

  def getDuel(self, duel_id: int):
    return self._execute(f'SELECT * FROM `duel` WHERE `duel_id`={duel_id}').fetchone()

  def updateDuelStatus(self, duel_id: int):
    self._execute(f'UPDATE `duel` SET status=1 WHERE `duel_id`={duel_id}')

  
  def getDueler(self, duel_id: int):
    query = f'SELECT * FROM `user` WHERE `in_duel_id`={duel_id}'
    return self._execute(query).fetchall()

  def handleExist(self, handle: str):
    query = f"SELECT COUNT(*) FROM `user` WHERE `cfhandle`='{handle}'";
    ret = self._execute(query).fetchone()['COUNT(*)']
    return ret > 0

  def getProblem(self, lo: int, hi: int):
    query = (f"SELECT * FROM `problem` WHERE `rating`<={hi} AND `rating`>={lo} "
              "ORDER BY RANDOM() LIMIT 1")
    ret = self._execute(query).fetchone()
    return ret

  def getUser(self, qid: int):
    query = (f"SELECT * FROM `user` WHERE `qid`={qid}")
    return self._execute(query).fetchone()



class Bot:
  def __init__(self, c, db):
    self.qid = c['bot_qid']
    self.cqhost = c['cqhost']
    self.db = db

  def sendGrpMsg(self, gid: int, text: str):
    try:
      print(requests.post(url=self.cqhost+'/send_group_msg',
                  params={'group_id': gid, 'message': text}).json())
    except Exception as error:
      print(error)

  def bindUser(self, sender: int, txt: list):
    qid = int(txt[1])
    handle = txt[2]
    rt = CF.userRating(handle)
    if db.handleExist(handle):
      return "the handle is already used"
    elif rt == None:
      return "cf user not found"
    elif sender != qid:
      return "your qid is incorrect"
    db.createUser(qid, handle, rt)
    return f"{handle}({rt}): done."

  def gimme(self, sender: int, difficulty=0):
    usr = self.db.getUser(sender)
    if difficulty == 0:
      p = self.db.getProblem(usr['rating']-200, usr['rating']+200)
    else:
      p = self.db.getProblem(difficulty, difficulty)
    if p == None:
      return 'problem of that difficulty not found'
    return (f'task: {p["name"]}\n'
            f'difficulty: {p["rating"]}\n'
            f'https://codeforces.com/contest/{p["contest_id"]}/problem/{p["index"]}')

  def duel_invite(self, sender: int, enemy: int):
    p1 = self.db.getUser(sender)
    if p1['in_duel_id'] != None:
      return 'you have a duel in-progress'
    p2 = self.db.getUser(enemy)
    if p2['in_duel_id'] != None:
      return 'they have a duel in-progress'
    r1, r2 = p1['rating'], p2['rating']
    lo, hi = min(r1, r2), max(r1, r2)
    p = self.db.getProblem(lo-500, hi+200)
    duel_id = self.db.createDuel(p['contest_id'], p['index'], p['rating'], sender, enemy)
    return f'invitation to {self.db.getUser(enemy)["cfhandle"]} sent'

  def duel_accept(self, sender: int):
    duel = self.db.getInvitedDuel(sender)
    p1, p2 = duel['player1'], duel['player2']
    c1, c2 = self.db.getUser(p1)['cfhandle'], self.db.getUser(p2)['cfhandle']
    duel_id = duel['duel_id']
    self.db.putInDuel(p1, duel_id)
    self.db.putInDuel(p2, duel_id)
    self.db.createEvent(p1['qid'], 0)
    self.db.createEvent(p2['qid'], 0)
    self.db.updateDuelStatus(duel_id)
    return (f'ok, {c1} and {c2} are now in duel.\n'
            f'task: https://codeforces.com/contest/{duel["p_contest_id"]}/problem/{duel["p_index"]}')

  def check_duel(self, sender: int):
    duel_id = self.db.getDuelId(sender)
    if duel_id == None:
      return 'you are not in duel'
    duelers = self.db.getDueler(duel_id)
    duel = self.db.getDuel(duel_id)

    fastest = None
    winner = None
    for x in duelers:
      y = CF.checkAC(x['cfhandle'], duel['p_contest_id'], duel['p_index'])
      if y != None:
        if fastest == None or fastest > y:
          winner = x
          fastest = y

    if winner == None:
      return 'there is no winner yet'

    loser = None
    for x in duelers:
      self.db.clearDuelStatus(x['qid'])
      if x != winner:
        loser = x
    
    delta = calDelta(winner['rating'], loser['rating'], duel['p_difficulty'])
    self.db.addRating(winner['qid'], delta)
    self.db.createEvent(winner['qid'], 1)
    self.db.setDuelWinner(duel_id, winner['qid'])

    return (f'on Duel{duel["duel_id"]}: [{winner["cfhandle"]}] VS [{loser["cfhandle"]}]\n'
            f'winner: {winner["cfhandle"]}\n'
            f'time: {timedelta(seconds=fastest-int(duel["duel_time"]))}\n'
            f'rating: {winner["rating"]} → {winner["rating"]+delta} (Δ: +{delta})')

  def duel_decline(self, sender: int):
    duel = self.db.getInvitedDuel(sender)
    if duel == None:
      return 'you are not in duel'
    p1 = self.db.getUser(duel['player1'])
    p2 = self.db.getUser(duel['player2'])
    self.db.updateDuelStatus(duel['duel_id'])
    return f"Duel{duel['duel_id']} between [{p1['cfhandle']}] and [{p2['cfhandle']}] is now rejected"

  def duel_skip(self, sender: int):
    duel_id = self.db.getDuelId(sender)
    if duel_id == None:
      return 'you are not in duel'
    duel = self.db.getDuel(duel_id)
    db.clearDuelStatus(sender)
    self.db.createEvent(sender, 2)
    td = timedelta(seconds=datetime.now(timezone.utc).timestamp() - int(duel['duel_time'])) 
    return f'you skip Duel{duel_id} after {td}'

  def get_info(self, sender: int):
    user = self.db.getUser(sender)
    win = self.db.getEventCount(sender, 1)
    skip = self.db.getEventCount(sender, 2)
    tot = self.db.getEventCount(sender, 0)
    return (f"{user['cfhandle']}({user['rating']})\n"
            f"duel: {win}/{skip}/{tot}")


  def process(self, gid: int, sender: int, text: str):
    txt = text.split()
    ret = ''
    if len(txt) == 0:
      return
    elif len(txt) == 3 and txt[0] == 'bind':
      ret = self.bindUser(sender, txt)
    elif len(txt) == 1 and txt[0] == 'gimme':
      ret = self.gimme(sender)
    elif len(txt) == 2 and txt[0] == 'gimme':
      ret = self.gimme(sender, txt[1])
    elif len(txt) == 1 and txt[0] == 'ping':
      ret = "pong!"
    elif len(txt) == 1 and txt[0] == 'accept':
      ret = self.duel_accept(sender)
    elif len(txt) == 2 and txt[0] == 'duel':
      ret = self.duel_invite(sender, txt[1])
    elif len(txt) == 1 and txt[0] == 'check':
      ret = self.check_duel(sender)
    elif len(txt) == 1 and txt[0] == 'skip':
      ret = self.duel_skip(sender)
    elif len(txt) == 1 and txt[0] == 'info':
      ret = self.get_info(sender)
    elif len(txt) == 1 and txt[0] == 'decline':
      ret = self.duel_decline(sender)
    if ret != '':
      self.sendGrpMsg(gid, ret)

def calDelta(r1: int, r2: int, d: int):
  e_a = 1.0/(1.0+10**((r2-r1)/400.0))
  k = 20
  return int((1.0*d/r1)**2 *  k * (1.0-e_a))



if __name__ == '__main__':
  with open('config.json', "r", encoding='utf-8') as file:
    config = json.load(file)

  db = DbConn()
  bot = Bot(config, db)

  app = Flask(__name__)
  @app.route('/', methods=["POST"])
  def mainLoop():
    msg = request.get_json()
    if msg.get('message_type') != 'group':
      return 'ok'
    sender = msg.get('sender').get('user_id')
    text = msg.get('raw_message')
    gid = int(msg.get('group_id'))
    bot.process(gid, sender, text)
    return 'ok'
  app.run(threaded=False, port=config['port'], host=config['host'])