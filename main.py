from bottle import route, request, run
import json
import os
import psycopg2
from psycopg2.extras import DictCursor
import random
import requests

# CONST
DSN = os.environ.get('DATABASE_URL')
CAT = os.environ.get('CHANNEL_ACCESS_TOKEN')
REPLY_EP = ""
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


# LINE API
def reply_message(body):
    req = requests.post(REPLY_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)
    return req


def broadcast_message(body):
    req = requests.post(BROADCAST_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)
    return req


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
    event_list = request.json['event']
    ret = []
    for event in event_list:
        event_type = event['type']
        reply_token = event['replyToken']
        if event_type == 'postback':
            pass
        elif event_type == 'message' and event['message']['type'] == 'text' and "問題" in event['message']['text']:
            ret.append(reply_question(reply_token))
        else:
            ret.append('OK')
    return '\n'.join(ret)


if __name__ == '__main__':
    run(host='0.0.0.0', port=os.environ.get('PORT', 443))
