from bottle import route, request, run, abort
import json
import os
from pprint import pformat, pprint
import psycopg2
from psycopg2.extras import DictCursor
import random
import requests

# CONST
DSN = os.environ.get('DATABASE_URL')
CAT = os.environ.get('CHANNEL_ACCESS_TOKEN')
REPLY_EP = "https://api.line.me/v2/bot/message/reply"
BROADCAST_EP = "https://api.line.me/v2/bot/message/broadcast"
DEFAULT_HEADER = {'Content-type': 'application/json', 'Authorization': f"Bearer {CAT}"}


# database API
def open_pg():
    return psycopg2.connect(DSN)


def get_question():
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from questions')
            questions = cur.fetchall()
    return dict(random.choice(questions))


def get_description(qid):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from questions where id = %s', (qid,))
            record = cur.fetchone()
    return dict(record)


# LINE API
def reply_message(body):
    return requests.post(REPLY_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def reply_text(text, token):
    body = {'messages': [{'type': 'text', 'text': text}],
            'replyToken': token}
    return reply_message(body)


def broadcast_message(body):
    return requests.post(BROADCAST_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def make_question_message(q):
    message = {'messages': [
        {'type': "text",
         'text': q['question'],
         'quickReply': {'items': [
             {'type': 'action',
              'action': {
                  'type': 'postback',
                  'label': "○",
                  'data': f"qid={q['id']}&answer=True",
                  'text': "○"
              }},
             {'type': 'action',
              'action': {
                  'type': 'postback',
                  'label': "×",
                  'data': f"qid={q['id']}&answer=False",
                  'text': "×"
              }}
         ]}}
    ]}
    return message


# callback
def check_answer(postback):
    token = postback['replyToken']
    data = postback['postback']['data']
    qid, ans = [p.split('=')[1] for p in data.split('&')]
    record = get_description(qid)
    text = "正解です！\n" if ans == str(record['answer']) else "不正解です！\n"
    text += f"【解説】\n{record['description']}"
    res = reply_text(text, token)
    if res.status_code == 200:
        return 'OK'
    else:
        return res.text


def pre_registration(token):
    form_id = os.environ.get('FORM_ID')
    target = "%27%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A0%E3%81%AE%E5%9B%9E%E7%AD%94%201%27!A1:E1000"
    ep = f"https://asia-northeast1-sheetstowebapi.cloudfunctions.net/api?id={form_id}&range={target}"
    req = requests.get(ep)
    questions = req.json()
    p_latest, c_latest = "", ""
    text = "現在予備登録されている問題一覧："
    for q in sorted(questions, key=lambda x: x['タイムスタンプ']):
        part = q['パートを選択']
        chapter = q['章番号（半角数字のみ）']
        number = q['問題番号（半角数字のみ）']
        if part != p_latest:
            text += '\n' + part + '\n'
            p_latest = part
        if chapter != c_latest:
            text += f"第{chapter}章\n"
            c_latest = chapter
        text += f"Q.{number} {q.get('問題文', '')[:5]}...\n"
    return reply_text(text, token)


def reply_question(token):
    q = get_question()
    q_message = make_question_message(q)
    q_message['replyToken'] = token
    res = reply_message(q_message)
    if res.status_code == 200:
        return 'OK'
    else:
        return res.text


# routing
@route('/question', method='POST')
def question():
    q = get_question()
    q_message = make_question_message(q)
    res = broadcast_message(q_message)
    if res.status_code == 200:
        return 'OK'
    else:
        return res.text


@route('/line-callback', method='POST')
def line_callback():
    event_list = request.json['events']
    ret = []
    for event in event_list:
        pprint(event)
        event_type = event['type']
        reply_token = event['replyToken']
        if event_type == 'postback':
            ret.append(check_answer(event))
        elif event_type == 'message' and event['message']['type'] == 'text':
            if "問題" in event['message']['text']:
                ret.append(reply_question(reply_token))
            elif event['message']['text'] == "登録":
                ret.append(reply_text(os.environ.get('FORM_URI'), reply_token))
            elif event['message']['text'] == "確認":
                ret.append(pre_registration(reply_token))
        else:
            ret.append('OK')
    return '\n'.join(ret)


@route('/db/check/<table>', method='GET')
def check_db(table='all'):
    debug = os.environ.get('DEBUG', False)
    if debug:
        with open_pg() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if table == 'all':
                    cur.execute('select relname from pg_class where relkind = r')
                    result = cur.fetchall()
                else:
                    cur.execute('select * from %s', (table,))
                    result = cur.fetchall()
        return pformat(dict(result))
    else:
        return abort(404)


if __name__ == '__main__':
    run(host='0.0.0.0', port=os.environ.get('PORT', 443))