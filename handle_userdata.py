import os

import json

import private.private_constants as pc


def join(link):
    return os.path.join(pc.ABS_PATH, link)


user_data = join("private/user_data.json")

VISITED = "visited"
ACTION_LOG = "action_log"


def load_user_db():
    if not os.path.exists(user_data):
        return dict()
    with open(user_data, 'r') as fp:
        db = json.load(fp)
    return db


def create_empty_entry():
    return {VISITED: [],
            ACTION_LOG: []}


def load_user_data(user_id):
    db = load_user_db()
    if user_id in db:
        return db[user_id]

    return create_empty_entry()


def save_user_data(user_id, user_db):
    db = load_user_db()
    db[user_id] = user_db
    with open(user_data, 'w') as fp:
        json.dump(db, fp)


def add_visited(user_id, machine_id):
    user_db = load_user_data(user_id)
    if machine_id in user_db[VISITED]:
        return False
    user_db[VISITED].append(machine_id)
    save_user_data(user_id, user_db)


def delete_visited(user_id, machine_id):
    user_db = load_user_data(user_id)
    if machine_id not in user_db[VISITED]:
        return False
    user_db[VISITED].remove(machine_id)
    save_user_data(user_id, user_db)


def delete_user_data(user_id):
    save_user_data(user_id, create_empty_entry())
