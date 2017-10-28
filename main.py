import os
import errno
import time
import subprocess
import pty
import threading
import pwd
import tweepy
from keys import *
import html


def html_to_unicode(escaped):
    return html.unescape(escaped)


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
            api.update_status(str(time.time()) + ': TwitBash online!')
            pass
        except tweepy.error.TweepError as e:
            print("Error sending bot online tweet.")
            print("Message: %s" % e)

    def on_disconnect(self, notice):
        print("Connection to twitter lost!! : ", notice)
        try:
            api.update_status(str(time.time()) + ': TwitBash now offline.')
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
                             (html_to_unicode(status.direct_message['text']) + '\n').encode())
                else:
                    api.send_direct_message(user_id=status.direct_message['sender_id'],
                                            text="Welcome %s to TwitBash, checking user state..." %
                                            status.direct_message['sender']['name'])

                    try:
                        pwd.getpwnam('twitbash-' + status.direct_message['sender_screen_name'])
                    except KeyError:
                        api.send_direct_message(user_id=status.direct_message['sender_id'],
                                                text="User does net exist. Setting up...")
                        subprocess.call(['useradd', 'twitbash-' + status.direct_message['sender_screen_name'],
                                         '-G', 'twitbash', '-m', '-k', '/etc/twitbash-skel'])
                        subprocess.call(['chmod', '700', '/home/twitbash-' + status.direct_message['sender_screen_name']])
                    api.send_direct_message(user_id=status.direct_message['sender_id'],
                                            text="Launching shell!")
                    master_fd, slave_fd = pty.openpty()
                    os.chdir("/home/twitbash-" + status.direct_message['sender_screen_name'])
                    process = subprocess.Popen(["su", "twitbash-" + status.direct_message['sender_screen_name']],
                                               stdin=slave_fd, stdout=slave_fd,
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
            api.update_status(str(time.time()) + ': TwitBash encountered an error... Now offline.')
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
        api.update_status(str(time.time()) + ': TwitBash now offline.')
        print('goodbye!')


if __name__ == '__main__':
    main()
