from bottle import route, request, run, template, abort
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
OK_STICKER = ((11537, 52002734), (11537, 52002735), (11537, 52002740), (11537, 52002748), (11537, 52002752),
              (11538, 51626498), (11538, 51626500), (11538, 51626501),
              (11539, 52114113), (11539, 52114117), (11539, 52114123))
NG_STICKER = ((11537, 52002744), (11537, 52002749), (11537, 52002753), (11537, 52002754), (11537, 52002760),
              (11537, 52002766), (11537, 52002769), (11537, 52002778), (11537, 52002779), (11538, 51626504),
              (11538, 51626506), (11538, 51626511), (11538, 51626515), (11538, 51626523), (11538, 51626526),
              (11539, 52114127), (11539, 52114129), (11539, 52114139), (11539, 52114144), (11539, 52114148))


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
    text = f"{q['part']} 第{q['chapter']}章 {q['number']}\n"
    text += q['question']
    message = {'messages': [
        {
            'type': 'template',
            'altText': text,
            'template': {
                'type': 'confirm',
                'text': text,
                'actions': [
                    {
                        'type': 'postback',
                        'label': "○",
                        'data': f"qid={q['id']}&answer=True",
                    },
                    {
                        'type': 'postback',
                        'label': "×",
                        'data': f"qid={q['id']}&answer=False",
                    }
                ]
            }
        }
    ]}
    return message


def make_answer_message(qid, ans, token):
    q = get_description(qid)
    stk = random.choice(OK_STICKER if ans == str(q['answer']) else NG_STICKER)
    text = f"{q['part']} 第{q['chapter']}章 {q['number']}\n"
    text += f"正解{'○' if q['answer'] else '×'}はです。\n"
    text += f"【解説】\n{q['description']}"
    message = {'messages': [
        {
            'type': 'sticker',
            'packageId': stk[0],
            'stickerId': stk[1]
        },
        {
            'type': 'text',
            'text': text
        }
    ], 'replyToken': token}
    return message


# callback
def check_answer(postback):
    token = postback['replyToken']
    data = postback['postback']['data']
    qid, ans = [p.split('=')[1] for p in data.split('&')]
    a_message = make_answer_message(qid, ans, token)
    res = reply_message(a_message)
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


@route('/list', method='GET')
def list_preregistered():
    form_id = os.environ.get('FORM_ID')
    target = "%27%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A0%E3%81%AE%E5%9B%9E%E7%AD%94%201%27!A1:E1000"
    ep = f"https://asia-northeast1-sheetstowebapi.cloudfunctions.net/api?id={form_id}&range={target}"
    req = requests.get(ep)
    questions = req.json()
    return template('questions-list', questions=sorted(questions, key=lambda x: x['タイムスタンプ']))


@route('/line-callback', method='POST')
def line_callback():
    debug = os.environ.get('DEBUG', False)
    event_list = request.json['events']
    ret = []
    for event in event_list:
        if debug:
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
    # FIXME: レスポンスの形式を統一させる。どのタイミングでテキストにするか。
    if debug:
        pprint('\n'.join(ret))
    return '\n'.join(ret)


# debug
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
