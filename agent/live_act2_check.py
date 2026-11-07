"""Finish Neow, stage an Act 1 boss win in the live game, then let the agent play on through the act change and the Hive."""
import sys
import time

from live import LiveGame

game = LiveGame(sys.argv[1], sys.argv[2])
game.client.full_restart()
while True:  # Neow, as in a real run
    s = game.client.state()
    game.run.sync(s)
    if s["screen"] == "map":
        break
    if s["screen"] == "event" and s.get("details"):
        game.do_event(s["details"])
    elif s["screen"] == "rewards":
        game.do_rewards(s["rewards"])
    elif s["screen"] == "choice":
        game.do_choice(s["choice"])
    else:
        time.sleep(0.25)
game.client.exec("close_map", settle=0.5)
print(game.client.exec("room Boss", settle=2.0))
game.client.wait_for(lambda c: c.get("inCombat") and c.get("isPlayPhase"), timeout=30.0)
print(game.client.exec("damage 40 0", settle=1.0))  # so the Ancient's heal shows
print(game.client.exec("win", settle=2.0))
print("cleared" if game.play(restart=False) else "died")
