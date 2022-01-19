import evdev
import threading
import time

_K = evdev.ecodes

KEY_PLAY = _K.KEY_PLAY
KEY_STOP = _K.KEY_STOP
KEY_PAUSE = _K.KEY_PAUSE
KEY_PLAYPAUSE = _K.KEY_PLAYPAUSE
KEY_PREVIOUS = _K.KEY_PREVIOUSSONG
KEY_NEXT = _K.KEY_NEXTSONG

_Desired = {k:None for k in [
    KEY_PLAY, KEY_STOP, KEY_PAUSE, KEY_PLAYPAUSE, KEY_PREVIOUS, KEY_NEXT,
    _K.KEY_PLAYCD, _K.KEY_STOPCD, _K.KEY_PAUSECD, _K.KEY_VOLUMEUP, _K.KEY_VOLUMEDOWN
]}
_Map = {_K.KEY_PLAYCD: KEY_PLAY, _K.KEY_STOPCD: KEY_STOP, _K.KEY_PAUSECD: KEY_PAUSE}

class ButtonScanner:
    def __init__(self, onPress):
        self.devices = {}
        self.onPress = onPress
        self.quitEvent = None

    def start(self):
        self.quitEvent = threading.Event()
        self.thread = threading.Thread(target=lambda: self._main(), name='ButtonScanner')
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        if self.quitEvent is not None:
            self.quitEvent.set()
            for t in self.devices.values():
                if t: t[0].close()
            self.devices.clear()
            self.thread.join()

    def _main(self):
        while True:
            sysDevices = evdev.list_devices()
            for name in self.devices.keys(): # close handles to devices that have disappeared
                if name not in sysDevices:
                    entry = self.devices[name]
                    if entry: entry[0].close()
                    self.devices.pop(name, None)

            for name in sysDevices: # and open handles to new devices that we're interested in
                if name not in self.devices:
                    try:
                        dev = evdev.InputDevice(name)
                        keys = dev.capabilities().get(_K.EV_KEY)
                        wanted = False # we want it if it can report any of the keys we're looking for
                        if keys:
                            for k in keys:
                                if k in _Desired:
                                    wanted = True
                                    break
                        if not wanted:
                            self.devices[name] = None # remember it for next time so we don't get its capabilities again
                            dev.close()
                        else:
                            thread = threading.Thread(target=lambda d: self._scan(d), name=name, args=(dev,))
                            self.devices[name] = (dev, thread)
                            thread.start()
                    except: pass

            if self.quitEvent.wait(5): break

    def _processKey(self, key):
       key = _Map.get(key, key)
       self.onPress(key)

    def _scan(self, dev):
        try:
            lastTime = {}
            for e in dev.read_loop():
                if e.type == _K.EV_KEY and e.value != 0 and e.code in _Desired: # value 0 is key up
                    now = e.timestamp()
                    if e.value == 1 or (e.value == 2 and now - lastTime.get(e.code, 0) >= 0.5): # key down
                        lastTime[e.code] = now
                        self._processKey(e.code)
        except:
            self.devices.pop(dev.path, None)
            dev.close()
