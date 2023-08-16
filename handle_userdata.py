import os

from datetime import datetime

import json

import private.private_constants as pc


def join(link):
    return os.path.join(pc.ABS_PATH, link)


user_data_db = join("private/user_data.json")

VISITED = "visited"
ACTION_LOG = "action_log"


def load_user_db():
    if not os.path.exists(user_data_db):
        return dict()
    with open(user_data_db, 'r') as fp:
        db = json.load(fp)
    return db


def create_empty_entry():
    return {VISITED: [],
            ACTION_LOG: []}


def load_chat_data(chat_id):
    chat_id = str(chat_id)
    db = load_user_db()
    if chat_id in db:
        return db[chat_id]

    return create_empty_entry()


def save_chat_data(chat_id, chat_data):
    chat_id = str(chat_id)
    db = load_user_db()
    if chat_id in db:
        del db[chat_id]
    db[chat_id] = chat_data
    with open(user_data_db, 'w') as fp:
        json.dump(db, fp, indent=2)


def add_visited(chat_id, machine_id):
    chat_data = load_chat_data(chat_id)
    if machine_id in chat_data[VISITED]:
        return False
    chat_data[VISITED].append(machine_id)
    save_chat_data(chat_id, chat_data)
    return True


def delete_visited(chat_id, machine_id):
    chat_data = load_chat_data(chat_id)
    if machine_id not in chat_data[VISITED]:
        return False
    chat_data[VISITED].remove(machine_id)
    save_chat_data(chat_id, chat_data)
    return True


def add_action(chat_id, action: str, successful: bool):
    chat_data = load_chat_data(chat_id)
    chat_data[ACTION_LOG].append((str(datetime.today()), action, successful))
    save_chat_data(chat_id, chat_data)


def delete_chat_data(chat_id):
    save_chat_data(chat_id, create_empty_entry())
