from bottle import route, request, run
import os
import requests


@route('/line-callback', method='POST')
def line_callback():
    return 'OK'


if __name__ == '__main__':
    run(host='0.0.0.0', port=os.environ.get('PORT', 443))
