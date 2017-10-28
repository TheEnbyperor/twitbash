import os
import errno
import time
import subprocess
import pty
import threading
import tweepy
from keys import *

auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
auth.set_access_token(access_token, access_token_secret)
api = tweepy.API(auth)

sessions = {}


def check_process(uid):
    session = sessions[uid]
    process = session["process"]
    master_fd = os.fdopen(session["fd"])
    try:
        while 1:
            try:
                line = master_fd.readline()
            except OSError as e:
                if e.errno != errno.EIO:
                    raise
                break  # EIO means EOF on some systems
            else:
                if not line:  # EOF
                    break
                api.send_direct_message(user_id=uid, text=line)
    finally:
        os.close(session["fd"])
        rc = process.poll()
        if rc is None:
            process.kill()
        else:
            api.send_direct_message(user_id=uid, text="Session finished with return code %s" % str(rc))
        process.wait()
        del sessions[uid]


class StdOutListener(tweepy.StreamListener):
    """Class that handles tweepy events.
E.g: on_connect, on_disconnect, on_status, on_direct_message, etc."""
    me = None

    def on_connect(self):
        print("Connection to twitter established!!")
        self.me = api.me()
        try:
            api.update_status('Chat bot online!')
            pass
        except tweepy.error.TweepError as e:
            print("Error sending bot online tweet.")
            print("Message: %s" % e)

    def on_disconnect(self, notice):
        print("Connection to twitter lost!! : ", notice)
        try:
            api.update_status('Chat bot bot now offline.')
        except tweepy.error.TweepError as e:
            print("Error sending bot offline tweet.")
            print("Message: %s" % e)

    def on_status(self, status):
        print(status.user.name + ": \"" + status.text + "\"")
        return True

    def on_event(self, status):
        if status.event == "follow":
            if status.source["id"] != self.me.id:
                print("Follow from %s" % status.source["screen_name"])
                api.create_friendship(status.source["id"])
                return True

    def on_direct_message(self, status):
        print("Direct message received.")
        try:
            if status.direct_message['sender_id'] != self.me.id:
                print(status.direct_message['sender_screen_name'] + ": \"" + status.direct_message['text'] + "\"")
                if sessions.get(status.direct_message['sender_id'], False):
                    os.write(sessions[status.direct_message["sender_id"]]["fd"],
                             (status.direct_message['text'] + '\n').encode())
                else:
                    master_fd, slave_fd = pty.openpty()
                    process = subprocess.Popen(["/bin/bash", "--login"], stdin=slave_fd, stdout=slave_fd,
                                               stderr=subprocess.STDOUT, close_fds=True)
                    os.close(slave_fd)
                    thread = threading.Thread(target=check_process, args=(status.direct_message['sender_id'],),
                                              daemon=True)
                    sessions[status.direct_message["sender_id"]] = {
                        "start_time": time.time(),
                        "last_message": time.time(),
                        "process": process,
                        "fd": master_fd,
                        "thread": thread
                    }
                    thread.start()
            return True
        except BaseException as e:
            print("Failed on_direct_message()", str(e))

    def on_error(self, status):
        print(status)
        try:
            api.update_status('Chat bot encountered an error... Now offline.')
        except tweepy.error.TweepError as e:
            print("Error sending bot offline-error tweet.")
            print("Message: %s" % e)


def main():
    try:
        me = api.me()
        print("Starting userstream for %s ( %s )" % (me.name, me.screen_name))
        stream = tweepy.Stream(auth, StdOutListener())
        stream.userstream()

    except (KeyboardInterrupt, SystemExit):
        print("Shutting down the twitter chatbot...")
        api.update_status('Chat bot bot now offline.')
        print('goodbye!')


if __name__ == '__main__':
    main()
