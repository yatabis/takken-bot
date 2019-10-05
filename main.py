from bottle import route, request, response, run, template, HTTPResponse
from datetime import datetime, timedelta
from io import BytesIO
import json
import matplotlib.pyplot as plt
import numpy as np
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
QUESTION_TIMES = (('first', 8), ('second', 10), ('third', 12), ('fourth', 14),
                  ('fifth', 16), ('sixth', 18), ('seventh', 20), ('eighth', 22))


# database API
def open_pg():
    return psycopg2.connect(DSN)


def get_users():
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select id from users')
            users = cur.fetchall()
    return [u[0] for u in users]


def get_question():
    with open_pg() as conn:
        q = None
        with conn.cursor(cursor_factory=DictCursor) as cur:
            while q is None:
                cur.execute('select * from questions where id = (select (max(id) * random())::int from questions) and cached = 0')
                q = cur.fetchone()
    return dict(q)


def get_description(qid):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from questions where id = %s', (qid,))
            record = cur.fetchone()
    return dict(record)


# def cached_decrement():
#     with open_pg() as conn:
#         with conn.cursor(cursor_factory=DictCursor) as cur:
#             cur.execute('update questions set cached = cached - 1 where cached != 0')
#
#
# def set_latest(qid):
#     cache_sise = os.environ.get('CACHE_SIZE', 10)
#     with open_pg() as conn:
#         with conn.cursor(cursor_factory=DictCursor) as cur:
#             cur.execute('update questions set cached = %s where id = %s', (cache_sise, qid))


def cache_update(qid):
    cache_sise = os.environ.get('CACHE_SIZE', 10)
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('update questions set cached = cached - 1 where cached != 0')
            cur.execute('update questions set cached = %s where id = %s', (cache_sise, qid))


def get_name(part=1, chapter=1, section=1):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select * from header_name where part = %s and chapter = %s and section = %s',
                        (int(part), int(chapter), int(section)))
            result = cur.fetchone()
    return result['part_name'], result['chapter_name'], result['section_name'], result['statement']


def upsert_score(uid: str, qid: str, ts: float, ans: bool):
    today = datetime.now()
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("select answer "
                        "from   questions "
                        "where  id = %s",
                        (qid,))
            is_correct = cur.fetchone()[0] is ans
            cur.execute("select answered, correct "
                        "from   scores "
                        "where  user_id = %s"
                        "   and year = %s"
                        "   and month = %s"
                        "   and day = %s",
                        (uid, today.year, today.month, today.day))
            score = cur.fetchone()
            if score is None:
                cur.execute("insert into scores "
                            "(user_id, year, month, day, answered, correct) "
                            "values (%s, %s, %s, %s, %s, %s)",
                            (uid, today.year, today.month, today.day, json.dumps([ts]), int(is_correct)))
            elif ts in json.loads(score["answered"]):
                return None
            else:
                tss = json.loads(score["answered"]) + [ts]
                correct = score["correct"] + int(is_correct)
                cur.execute("update scores set "
                            "answered = %s,"
                            "correct = %s "
                            "where  user_id = %s"
                            "   and year = %s"
                            "   and month = %s"
                            "   and day = %s",
                            (json.dumps(tss), correct, uid, today.year, today.month, today.day))
    return is_correct


def get_score_today(uid):
    today = datetime.now()
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("select answered, correct "
                        "from   scores "
                        "where  user_id = %s"
                        "   and year = %s"
                        "   and month = %s"
                        "   and day = %s",
                        (uid, today.year, today.month, today.day))
            score = cur.fetchone()
    if score is None:
        return "本日はまだ問題に解答していません。"
    answered = len(json.loads(score["answered"]))
    correct = score["correct"]
    rate = int(correct / answered * 1000) / 10
    goal80 = 4 * answered - 5 * correct
    goal90 = 9 * answered - 10 * correct
    text = f"本日のスコアです。\n正解した問題は{correct}問で、正答率は{rate}%です。"
    if rate < 80:
        text += f"\n正答率80%を達成するためにはこの後{goal80}問正解する必要があります。"
    if rate < 90:
        text += f"\n正答率90%を達成するためにはこの後{goal90}問正解する必要があります。"
    if rate >= 90:
        text += "\nいい調子です！"
    else:
        text += "\n頑張りましょう！"
    return text


def fetch_scores(user):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select year, month, day, answered, correct '
                        'from   scores '
                        'where  user_id = %s '
                        'order by year, month, day',
                        (user,))
            scores = cur.fetchall()
    return scores


def daily_report():
    date = datetime.today() - timedelta(days=1)
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute('select user_id, answered, correct '
                        'from   scores '
                        'where  year = %s'
                        '   and month = %s'
                        '   and day = %s',
                        (date.year, date.month, date.day))
            scores = cur.fetchall()
    for s in scores:
        answered = len(json.loads(s.get("answered")))
        correct = int(s.get("correct"))
        rate = int(correct / answered * 1000) / 10 if correct < answered else 100
        text = "本日の最終スコアを発表します。\n"
        text += f"解答数　{answered:>3}問\n"
        text += f"正解数　{correct:>3}問\n"
        text += f"不正解数{answered - correct:>3}問\n"
        text += f"正答率は {rate:>4}% でした。"
        user = s.get("user_id")
        push_message({
            "to": user,
            "messages": [
                {
                    "type": "text",
                    "text": text
                },
                {
                    "type": "image",
                    "originalContentUrl": f"https://takken-bot.herokuapp.com/scores/{user}",
                    "previewImageUrl": f"https://takken-bot.herokuapp.com/scores/{user}",
                }
            ]
        })


# LINE API
def push_message(body):
    return requests.post(PUSH_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def reply_message(body):
    return requests.post(REPLY_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER)


def reply_text(text, token):
    body = {'messages': [{'type': 'text', 'text': text}], 'replyToken': token}
    return reply_message(body)


def broadcast_message(body):
    res = []
    for u in get_users():
        body['to'] = u
        res.append(requests.post(PUSH_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers=DEFAULT_HEADER))
    return res


def make_question_message(q, timestamp):
    with open("question_message.json") as j:
        message = json.load(j)
    part, chapter, section, statement = get_name(q['part'], q['chapter'], q['section'])
    if (q['part'], q['chapter'], q['section']) == (1, 7, 2) and q['number'] >= 9:
        statement = ("AからBとCとが負担部分2分の1として連帯して1,000万円を借り入れる場合と、"
                     "DからEが1,000万円を借り入れ、Fがその借入金返済債務についてEと連帯して保証する場合とに関して考える。")
    message['header']['contents'][0]['text'] = part
    message['header']['contents'][1]['text'] = f"第{q['chapter']}章 『{chapter}』"
    if section:
        message['header']['contents'][2]['text'] = f"{q['section']}. {section}"
    else:
        message['header']['contents'] = message['header']['contents'][:2]
    message['body']['contents'][0]['text'] = f"問{q['number']}-{q['variation']}"
    message['body']['contents'][1]['text'] = statement + q['question'] if statement else q['question']
    message['footer']['contents'][0]['action']['data'] = f"qid={q['id']}&timestamp={timestamp}&answer=True"
    message['footer']['contents'][1]['action']['data'] = f"qid={q['id']}&timestamp={timestamp}&answer=False"
    return {'type': 'flex', 'altText': q['question'], 'contents': message}


def make_answer_message(qid, judge, token):
    q = get_description(qid)
    stk = random.choice(OK_STICKER if judge else NG_STICKER)
    part, chapter, section, statement = get_name(q['part'], q['chapter'], q['section'])
    text = f"【{part}】\n第{q['chapter']}章 『{chapter}』\n"
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
    ], 'replyToken': token}
    return message


def make_kakomon_message(token):
    with open("kakomon_message.json") as j:
        message = json.load(j)
    return {'messages': [{'type': 'flex', 'altText': "過去問演習", 'contents': message}], 'replyToken': token}


# callback
def check_answer(postback):
    user_id = postback['source']['userId']
    token = postback['replyToken']
    qid, timestamp, ans = [p.split('=')[1] for p in postback['postback']['data'].split('&')]
    is_correct = upsert_score(user_id, qid, float(timestamp), ans == "True")
    if is_correct is None:
        q = get_description(qid)
        text = f"{q['part']} 第{q['chapter']}章 問{q['number']}-{q['variation']}\n"
        text += f"正解は{'○' if q['answer'] else '×'}です。\n"
        text += f"{q['description']}"
        res = reply_text(text, token)
    else:
        a_message = make_answer_message(qid, is_correct, token)
        res = reply_message(a_message)
    if res.status_code == 200:
        return 'OK'
    else:
        return res.text


def reply_question(token):
    q = get_question()
    q_message = {
        "messages": [make_question_message(q, datetime.now().timestamp())],
        "replyToken": token
    }
    res = reply_message(q_message)
    if res.status_code == 200:
        return 'OK'
    else:
        return res.text


# routing
@route('/question', method='POST')
def question():
    time = datetime.now()
    hour, minute = time.hour, time.minute
    if hour == 0 and minute < 10:
        daily_report()
        return "scores are reported."
    if hour not in [t[1] for t in QUESTION_TIMES] or minute // 10 > 0:
        return 'This is not question time.'
    q_message = {"messages": []}
    for i in range(3):
        q = get_question()
        q_message["messages"].append(make_question_message(q, datetime.now().timestamp()))
        # cached_decrement()
        # set_latest(q['id'])
        cache_update(q['id'])
    res = broadcast_message(q_message)
    if False not in [r.status_code == 200 for r in res]:
        return 'OK'
    else:
        return " and ".join([r.text for r in res])


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
            if event["postback"]["data"] == "question":
                ret.append(reply_question(reply_token))
            elif event["postback"]["data"] == "score":
                reply_text(get_score_today(event["source"]["userId"]), reply_token)
            else:
                ret.append(check_answer(event))
        elif event_type == 'message' and event['message']['type'] == 'text':
            if "問題" in event['message']['text']:
                ret.append(reply_question(reply_token))
            elif "成績" in event['message']['text']:
                ret.append(reply_text(get_score_today(event["source"]["userId"]), reply_token))
            elif "過去問" in event['message']['text']:
                ret.append(reply_message(make_kakomon_message(reply_token)))
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


@route('/scores/<user>', method="GET")
def make_score_graph(user):
    scores = fetch_scores(user)
    buf = BytesIO()
    graph = np.zeros((3, len(scores)), dtype=np.int)
    labels = [""] * len(scores)
    for i, s in enumerate(scores):
        date = datetime(s.get("year"), s.get("month"), s.get("day"))
        labels[i] = date.strftime("%b %-d\n%Y") if date.day % 3 == 1 else ""
        graph[0][i] = (date - datetime(2019, 9, 6)).days
        graph[1][i] = len(json.loads(s.get("answered")))
        graph[2][i] = s.get("correct")
    fig, ax1 = plt.subplots()
    ax1.bar(graph[0], graph[1], width=0.3, align='center', tick_label=labels)
    ax1.bar(graph[0], graph[2], width=0.3, align='center', tick_label=labels)
    ax2 = ax1.twinx()
    rate = 100 * graph[2] / graph[1]
    ax2.plot(graph[0], rate, color="red", linewidth=3, marker="o")
    ax2.set_ylim(0, 100)
    plt.savefig(buf, format="png")
    response.content_type = "image/png"
    return buf.getvalue()


@route('/kakomon', method="GET")
def kakomon():
    return template("kakomon.html")


@route('/kakomon/<year>', method="GET")
def kakomon_answer(year):
    with open_pg() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("select * "
                        "from   kakomon "
                        "where  year = %s",
                        (f"H{year}",))
            correct = cur.fetchone()
    if correct is None:
        return HTTPResponse(status=404, body="エラー")
    return HTTPResponse(status=200, body={"correct": list(correct)[1:]}, headers={"Content-Type": "application/json"})


if __name__ == '__main__':
    run(host='0.0.0.0', port=os.environ.get('PORT', 443))
