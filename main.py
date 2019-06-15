from bottle import route, request, run, template, abort
from datetime import datetime
import json
from operator import itemgetter
import os
from pprint import pformat, pprint
import psycopg2
from psycopg2.extras import DictCursor
import random
import requests

# CONST
DSN = os.environ.get('DATABASE_URL')
CAT = os.environ.get('CHANNEL_ACCESS_TOKEN')
PUSH_EP = "https://api.line.me/v2/bot/message/push"
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
            cur.execute('select * from questions where cached = 0')
            questions = cur.fetchall()
    return dict(random.choice(questions))


def get_description(qid):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from questions where id = %s', (qid,))
            record = cur.fetchone()
    return dict(record)


def cached_decrement():
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('update questions set cached = cached - 1 where cached != 0')


def set_latest(qid):
    cache_sise = os.environ.get('CACHE_SIZE', 10)
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('update questions set cached = %s where id = %s', (cache_sise, qid))


def is_answered(user, hour):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from users where id = %s', (user, ))
            # cur.execute('select %s from users where id = %s', (str(hour), user))
            result = cur.fetchone()
    return dict(result)[str(hour)]


def get_name(part=1, chapter=1, section=1):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from header_name where part = %s and chapter = %s and section = %s',
                        (int(part), int(chapter), int(section)))
            result = cur.fetchone()
    return result['part_name'], result['chapter_name'], result['section_name'], result['statement']


def set_judge(user, hour, judge):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('update users set "%s" = %s where id = %s', (int(hour), judge, user))


def reset_judge():
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(
                'update users set '
                '("7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23") = '
                '(NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)'
            )


def daily_report():
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from users')
            all_scores = cur.fetchall()
    for score in all_scores:
        text = f"お疲れ様でした。\n本日の{score['name']}さんのスコアです。\n"
        report = []
        t, f, n, judge = 0, 0, 0, ""
        for h in range(7, 23 + 1):
            s = score[str(h)]
            if s is True:
                judge = "○"
                t += 1
            elif s is False:
                judge = "×"
                f += 1
            elif s is None:
                judge = "-"
                n += 1
            report.append(f"{h:>2}時：{judge}")
        text += f"　正解：{t}問\n不正解：{f}問\n未解答：{n}問\n"
        if n > 8:
            text += "継続は力なり、毎日コツコツ問題を解きましょう。"
        elif t >= 17:
            text += "その調子です！頑張っていきましょう。"
        else:
            text += "しっかりと復習をして定着させていきましょう。"
        push_message(make_report_message(text, '\n'.join(report), score['id']))


def record_scores():
    today = datetime.today()
    year = today.year
    month = today.month
    day = today.day - 1
    print(year, month, day)
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from users')
            all_scores = cur.fetchall()
            for score in all_scores:
                print(score['name'])
                uid = score['id']
                values = list(score.values())
                t = values.count(True)
                f = values.count(False)
                n = values.count(None)
                cur.execute('insert into scores '
                            '(line_id, y, m, d, t, f, n) values '
                            '(%s, %s, %s, %s, %s, %s, %s)',
                            (uid, year, month, day, t, f, n))


# LINE API
def push_message(body):
    return requests.post(PUSH_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def reply_message(body):
    return requests.post(REPLY_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def reply_text(text, token):
    body = {'messages': [{'type': 'text', 'text': text}],
            'replyToken': token}
    return reply_message(body)


def broadcast_message(body):
    return requests.post(BROADCAST_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def make_question_message(q, on_time=True):
    hour = datetime.now().hour if on_time else 'immediate'
    part, chapter, section, statement = get_name(q['part'], q['chapter'], q['section'])
    text = f"【{part}】\n第{q['chapter']}章 『{chapter}』\n"
    if section:
        text += f"{q['section']}. {section}\n"
    text += f"問{q['number']}-{q['variation']}\n"
    if statement:
        text += statement + '\n'
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
                        'data': f"qid={q['id']}&hour={hour}&answer=True",
                    },
                    {
                        'type': 'postback',
                        'label': "×",
                        'data': f"qid={q['id']}&hour={hour}&answer=False",
                    }
                ]
            }
        }
    ]}
    return message


def make_answer_message(qid, ans, uid):
    q = get_description(qid)
    judge = ans == str(q['answer'])
    stk = random.choice(OK_STICKER if judge else NG_STICKER)
    part, chapter, section, statement = get_name(q['part'], q['chapter'], q['section'])
    text = f"{part}\n第{q['chapter']}章 {chapter}\n"
    if section:
        text += f"{q['section']}. {section}\n"
    text += f"問{q['number']}-{q['variation']}\n"
    text += f"正解は{'○' if q['answer'] else '×'}です。\n"
    text += f"{q['description']}"
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
    ], 'to': uid}
    return message, judge


def make_report_message(text, report, uid):
    message = {'messages': [
        {'type': 'text', 'text': text},
        {'type': 'text', 'text': report}
    ], 'to': uid}
    return message


# callback
def check_answer(postback):
    user_id = postback['source']['userId']
    token = postback['replyToken']
    qid, hour, ans = [p.split('=')[1] for p in postback['postback']['data'].split('&')]
    if not (hour == 'immediate' or is_answered(user_id, hour) is None):
        q = get_description(qid)
        text = f"{q['part']} 第{q['chapter']}章 問{q['number']}-{q['variation']}\n"
        text += f"正解は{'○' if q['answer'] else '×'}です。\n"
        text += f"{q['description']}"
        res = reply_text(text, token)
    else:
        reply_text("あなたの解答：" + ("○" if eval(ans) else "×"), token)
        a_message, judge = make_answer_message(qid, ans, user_id)
        res = push_message(a_message)
        set_judge(user_id, hour, judge)
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
    q_message = make_question_message(q, on_time=False)
    q_message['replyToken'] = token
    res = reply_message(q_message)
    if res.status_code == 200:
        return 'OK'
    else:
        return res.text


# routing
@route('/question', method='POST')
def question():
    hour = datetime.now().hour
    if hour == 0:
        daily_report()
        record_scores()
    if hour == 0 or hour == 7:
        reset_judge()
    if not 7 <= hour <= 23:
        return 'night'
    q = get_question()
    q_message = make_question_message(q)
    res = broadcast_message(q_message)
    if res.status_code == 200:
        cached_decrement()
        set_latest(q['id'])
        return 'OK'
    else:
        return res.text


@route('/list', method='GET')
def list_preregistered():
    form_id = os.environ.get('FORM_ID')
    target = "%27%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A0%E3%81%AE%E5%9B%9E%E7%AD%94%201%27!A1:E1000"
    ep = f"https://asia-northeast1-sheetstowebapi.cloudfunctions.net/api?id={form_id}&range={target}"
    req = requests.get(ep)
    pre_registered = req.json()
    registered = sorted(check_questions(), key=itemgetter('part', 'chapter', 'number', 'variation'))
    return template('questions-list',
                    registered=registered,
                    pre_registered=sorted(pre_registered, key=lambda x: x['タイムスタンプ']))


@route('/line-callback', method='POST')
def line_callback():
    # if os.environ.get('MENTAINANCE', False)
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
@route('/db/check/questions', method='GET')
def check_questions():
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from questions')
            result = cur.fetchall()
    return [dict(r) for r in result]


if __name__ == '__main__':
    run(host='0.0.0.0', port=os.environ.get('PORT', 443))
