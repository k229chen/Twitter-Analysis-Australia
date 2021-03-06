import requests
import json
import tweepy
from datetime import datetime
from tokens import credential
from random import choice
from itertools import islice
from concurrent.futures import ThreadPoolExecutor
import couchdb


class DotDict(dict):
    '''dot.notation access to dictionary attributes'''

    def __getattr__(*args):
        val = dict.__getitem__(*args)
        return DotDict(val) if type(val) is dict else val

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def parse_line(line):
    try:
        line = str(line, encoding='utf-8').strip()
        if line.endswith(','):
            line = line[:-1]
        return DotDict(json.loads(line))
    except json.decoder.JSONDecodeError:
        pass


def stream(url, func=requests.get, stream=True):
    with func(url, stream=stream) as r:
        yield from filter(None, map(parse_line, r.iter_lines()))


def split_every(iterable, chunk=100):
    i = iter(iterable)
    piece = list(islice(i, chunk))
    while piece:
        yield piece
        piece = list(islice(i, chunk))


# return a random authorized twitter api if did not specify accurate token info
def api(index=None, wait_on_rate_limit=True, wait_on_rate_limit_notify=True, token=None):
    if index:
        token = credential[index]
    elif not token:
        token = choice(credential)
    auth = tweepy.OAuthHandler(token['consumer_key'],
                               token['consumer_secret'])
    auth.set_access_token(token['access_token_key'],
                          token['access_token_secret'])
    return tweepy.API(auth, wait_on_rate_limit=wait_on_rate_limit, wait_on_rate_limit_notify=wait_on_rate_limit_notify)


def db(name='tweets', url='172.26.131.114:5984', username='admin', password='admin'):
    return couchdb.Server(f'http://{username}:{password}@{url}').__getitem__(name)


def bulk_parse_tweet(raw_tweets, blacklist=['googuns_lulz', 'object82']):
    return list(filter(None, [parse_tweet(t, blacklist) for t in raw_tweets]))


def parse_tweet(raw_tweet, blacklist=['googuns_lulz', 'object82']):
    if not (raw_tweet.get('place') and raw_tweet['place']['country_code'] == 'AU'):
        return

    data = {}
    data['_id'] = f"{raw_tweet['user']['id_str']}:{raw_tweet['id_str']}"
    data['date'] = datetime.strptime(
        raw_tweet['created_at'], '%a %b %d %H:%M:%S %z %Y').strftime('%Y-%m-%d %H:%M:%S%z')
    data['user'] = raw_tweet['user']['screen_name']
    data['lang'] = raw_tweet['lang']

    if data['user'] in blacklist:
        return

    def extract_hashtag(entity):
        return [h['text'] for h in entity['hashtags']]

    # extended tweet is un-truncated version of the tweet
    if 'extended_tweet' in raw_tweet:
        ext = raw_tweet['extended_tweet']
        data['text'] = ext['full_text']
        data['hashtags'] = extract_hashtag(ext['entities'])
    else:
        data['text'] = raw_tweet['text']
        data['hashtags'] = extract_hashtag(raw_tweet['entities'])

    # geo-location
    if raw_tweet['coordinates'] and 'coordinates' in raw_tweet['coordinates']:
        data['geo'] = raw_tweet['coordinates']['coordinates']
    elif raw_tweet['geo'] and 'coordinates' in raw_tweet['geo']:
        coordinate = raw_tweet['geo']['coordinates']
        if len(coordinate) == 2:
            data['geo'] = [coordinate[1], coordinate[0]]
    else:
        return

    return data


def bulk_parse_user(raw_users, level=0):
    return list(filter(None, [parse_user(u, level) for u in raw_users]))


def parse_user(raw_user, level=0):
    user = {}
    user['_id'] = raw_user['id_str']
    user['name'] = raw_user['screen_name']
    user['level'] = level
    user['expanded'] = False
    user['searched'] = False
    for key in ['followers_count', 'friends_count', 'statuses_count']:
        user[key] = raw_user[key]

    activity = user['followers_count'] + user['friends_count']

    return None if \
        activity < 300 or \
        activity > 5000 or \
        raw_user['protected'] or \
        user['statuses_count'] > 100000 \
        else user


def bulk_update_by_id(db, ids, chunk_size=1500, **args):
    success = 0
    for chunk in split_every(ids, chunk_size):
        docs = [r.doc for r in db.view(
            '_all_docs', keys=chunk, include_docs=True)]
        for doc in docs:
            for k, v in args.items():
                doc[k] = v
        result = db.update(docs)
        success += sum([r[0] for r in result])
        print(f'{success}/{len(ids)} updated.')


def update_by_id(db, id, **args):
    doc = db.view('_all_docs', key=id, include_docs=True).rows[0].doc
    for k, v in args.items():
        doc[k] = v
    db.save(doc)
