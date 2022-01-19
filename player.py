import bluetooth
import buttons
import display
import json
import library
import os
import queue
import random
import re
import signal
import subprocess
import sys
import urllib.parse
import vlc

_C = display.Display
_Background = _C.Black
_Selected = _C.White
_Unselected = _C.Gray
_numRe = re.compile('^[0-9]+ - ')

class Menu:
    def deinit(self): self.leave()
    def init(self, ui):
        self.ui = ui
        self.d = ui.display
        self.enter(True)
    def enter(self, firstTime): self.paint()
    def leave(self): pass
    def onBtEvent(self, dev, op): pass
    def onPress(self, btn): pass
    def paint(self):
        self.ui.clear()
        self.d.flip()
    def tick(self): pass

    def center(self, item, color, font=None, y=None):
        if type(item) == str: item = self.measure(item, font)
        if y is None: y = (self.d.height - item[0]) // 2
        startY = y
        for line, w, h in item[1]:
            self.d.text((self.d.width-w) // 2, y, line, color, font)
            y += h
        return (startY, item[0])

    def measure(self, s, font=None):
        (w,h) = self.d.textsize(s, font)
        if w <= self.d.width: return (h,((s,w,h),))
        words = s.split()
        (i, x, h, lh, line, lines) = (0, 0, 0, 0, '', [])
        while i < len(words):
            bit = ' '+words[i] if line else words[i]
            (w,bh) = self.d.textsize(bit, font)
            x += w
            lh = max(lh, bh)
            wrap = x > self.d.width
            if not line: line = bit
            elif not wrap: line += bit
            else: x -= w
            if wrap:
                lines.append((line, x, lh))
                line = words[i]
                x = w
                h += lh
                lh = bh
            i += 1
        if line:
            lines.append((line, x, lh))
            h += lh
        return (h,lines)

class LoadingMenu(Menu):
    def paint(self):
        self.d.center('Loading...', _C.White)
        self.d.flip()

class ListMenu(Menu):
    class _collapsed:
        def __init__(self, keys, group=None):
            self.keys = keys
            self.group = group

    def __init__(self):
        self.collapse = False
        self.sort = True
        self.keepIndex = False
        self.keys = None
        self.index = 0
        self.stack = None

    def enter(self, firstTime):
        if firstTime: self.refreshList(False)
        super().enter(firstTime)

    def getItems(self): return {}

    def onPress(self, btn):
        newIndex = self.index
        repaint = False
        if btn == _C.U: newIndex = max(0, newIndex-1)
        elif btn == _C.D: newIndex = min(len(self.keys)-1, newIndex+1)
        elif btn == _C.L: newIndex = max(0, newIndex-8)
        elif btn == _C.R: newIndex = min(len(self.keys)-1, newIndex+8)
        elif btn == _C.A or btn == _C.C:
            value = self.items[self.keys[newIndex]]
            if self.collapse and isinstance(value, ListMenu._collapsed):
                self._setList({k:self.origItems[k] for k in value.keys}, len(self.stack)+1 if self.stack else 1, value.group)
                (newIndex, repaint) = (0, True)
            else:
                self.onSelected(self.keys[newIndex], value, btn)
        elif btn == _C.B:
            if self.stack and len(self.stack):
                (newIndex, self.items, self.keys) = self.stack.pop()
                repaint = True
            else:
                self.ui.pop()
        if newIndex != self.index:
            self.index = newIndex
            repaint = True
        if repaint: self.paint()

    def onSelected(self, key, value, btn): pass

    def paint(self):
        self.ui.clear()
        if len(self.keys):
            Spacing = 4
            (y,h) = self.center(self.keys[self.index], _Selected)
            btm = y+h
            i = self.index-1
            while i >= 0 and y >= Spacing:
                item = self.measure(self.keys[i], self.ui.smallFont)
                y = y - item[0] - Spacing
                self.center(item, _Unselected, self.ui.smallFont, y)
                i -= 1
            (i,y) = (self.index+1, btm+Spacing)
            while i < len(self.keys) and y < self.d.height:
                h = self.center(self.keys[i], _Unselected, self.ui.smallFont, y)[1]
                y += h + Spacing
                i += 1
        self.d.flip()

    def refreshList(self, repaint=True):
        oldKey = None
        if not self.keepIndex and self.keys is not None and len(self.keys): oldKey = self.keys[self.index]
        self._setList(self.getItems())
        if self.keepIndex:
            self.index = max(0, min(len(self.keys)-1, self.index))
        elif oldKey is not None:
            try: self.index = self.keys.index(oldKey)
            except: self.index = 0
        else:
            self.index = 0
        if repaint: self.paint()

    def _setList(self, items, depth=0, prevBucket=None):
        if depth:
            if self.stack is None: self.stack = []
            self.stack.append((self.index, self.items, self.keys))
        self.items = items
        self.keys = list(items.keys())
        (count, threshold) = (len(items), 10 if self.collapse == 'substr' else 20)
        if self.collapse and count > threshold:
            buckets = {}
            if self.collapse == 'substr':
                letters = '0123456789abcdefghijklmnopqrstuvwxyz'
                if depth: letters = ' ' + letters
                for c in letters:
                    sub = prevBucket + c if prevBucket else c
                    rgx = re.compile(r'\b' + sub, re.I) # pure substring search is a bit weird so use the starts of words
                    bucket = [key for key in self.keys if rgx.search(key)]
                    if len(bucket): buckets[sub] = bucket
            else:
                keyfn = lambda prefix: prefix + '...'
                for key in self.keys:
                    prefix = (key if key[0] != '(' else key.lstrip('('))[0:depth+1]
                    prefix = prefix[0].upper() + prefix[1:].lower() # normalize case so 'A' and 'a' are treated as the same prefix
                    L = buckets.get(prefix)
                    if L is None: buckets[prefix] = L = []
                    L.append(key)

            if depth == 0: (self.origItems, self.origKeys) = (self.items, self.keys)
            self.keys = []
            self.items = {}

            if self.collapse == 'substr':
                dedup = {}
                for bucket, L in buckets.items():
                    if len(L) > 2:
                        key = '...' + bucket.upper() + '...'
                        self.keys.append(key)
                        self.items[key] = ListMenu._collapsed(L, bucket)
                        for k in L: dedup[k] = None
                    else:
                        for k in L:
                            if k not in dedup:
                                self.keys.append(k)
                                self.items[k] = self.origItems[k]
                                dedup[k] = None
            else:
                for bucket, L in sorted(buckets.items(), key=lambda i: len(i[1]), reverse=True):
                    if count > threshold and len(L) > 2:
                        key = bucket + '...'
                        self.keys.append(key)
                        self.items[key] = ListMenu._collapsed(L, bucket)
                        count -= len(L)-1 # how many items did we save?
                    else:
                        self.keys.extend(L)
                        for k in L: self.items[k] = self.origItems[k]

        if self.sort: self.keys.sort(key=str.casefold)

class BluetoothMenu(ListMenu):
    def deinit(self):
        self.ui.scanner.stopScan()
        super().deinit()

    def init(self, ui):
        super().init(ui)
        self.ui.scanner.startScan()

    def getItems(self):
        devices = {dev.name: dev.addr for dev in self.ui.scanner.devices.values() if self._isAudioSink(dev)}
        return devices if len(devices) != 0 else {'Scanning...': None}

    def onBtEvent(self, dev, op): self.refreshList()

    def onSelected(self, key, value, btn):
        if value is not None: self.ui.push(DeviceMenu(value))

    def _isAudioSink(self, dev):
        return bluetooth.AUDIO_SINK in dev.uuids if len(dev.uuids) else (dev.cls & 0x200400) == 0x200400

class DeviceMenu(ListMenu):
    def __init__(self, addr):
        super().__init__()
        self.addr = addr
        self.sort = False
        self.keepIndex = True

    def getItems(self):
        dev = self._getDevice()
        if dev is None:
            self.ui.pop()
            return {}
        return {'Disconnect' if dev.connected else 'Connect': None,
                'Forget' if dev.paired else 'Pair': None,
                'Untrust' if dev.trusted else 'Trust': None}

    def onBtEvent(self, dev, op):
        if dev.addr == self.addr:
            if op == 'D': self.ui.pop()
            else: self.refreshList()

    def onSelected(self, key, value, btn):
        if key == 'Connect': self.ui.scanner.connect(self.addr)
        elif key == 'Disconnect': self.ui.scanner.disconnect(self.addr)
        elif key == 'Pair': self.ui.scanner.pair(self.addr)
        elif key == 'Forget': self.ui.scanner.remove(self.addr)
        elif key == 'Trust': self.ui.scanner.trust(self.addr)
        elif key == 'Untrust': self.ui.scanner.untrust(self.addr)

    def _getDevice(self): return self.ui.scanner.devices.get(self.addr)

class RootMenu(Menu):
    def enter(self, firstTime):
        super().enter(firstTime)
        if firstTime and self.ui.playlist.isempty(): self.ui.push(MainMenu())

    def init(self, ui):
        self._numHeight = ui.display.textsize('0123456789:')[1]
        super().init(ui)

    def onPress(self, btn):
        if btn == _C.U or btn == _C.D:
            if btn == _C.U: self.ui.previousTrack()
            elif btn == _C.D: self.ui.nextTrack(canRewind=True)
        elif btn == _C.L or btn == _C.R:
            if self.ui.player.is_playing():
                media = self.ui.player.get_media()
                duration = media.get_duration()
                pos = max(0, self.ui.player.get_position()) * duration
                newpos = max(0, min(duration, pos + (-5000 if btn == _C.L else 5000)))
                self.ui.player.set_position(newpos / duration)
                self.paint()
        elif btn == _C.A or btn == _C.C:
            current = self.ui.playlist.getCurrent()
            if current is None: self.ui.push(MainMenu())
            else: self.ui.playSong(current, toggle=True)
        elif btn == _C.B: self.ui.push(MainMenu())

    def paint(self):
        self.ui.clear()
        song = self.ui.playlist.getCurrent()
        if not song:
            self.d.center('Empty playlist', _C.White)
        else:
            def timeStr(ms):
                ts = int(ms*0.001 + 0.5)
                mins = ts // 60
                secs = ts - mins*60
                return str(mins) + ':' + str(secs).zfill(2)

            title = self.measure(song.title, self.ui.bigFont)
            artist = self.measure(song.artist)
            y = (self.d.height - 6 - self._numHeight - title[0] - artist[0]) // 2
            self.center(artist, _C.Gray, y=y)
            self.center(title, _C.White, self.ui.bigFont, y + artist[0] + 2)

            media = self.ui.ensureMedia(song)
            duration = media.get_duration()
            if duration > 0:
                frac = max(0, self.ui.player.get_position())
                pos = frac * duration
                remStr = timeStr(duration - pos)
                (w, y) = (self.d.textsize(remStr)[0], self.d.height - self._numHeight - 4)
                if pos > 0: self.d.rect(0, y - 1, int(self.d.width*frac), self.d.height - (y-1), (32, 48, 128))
                self.d.text(1, y, timeStr(pos), _C.White)
                self.d.text(self.d.width-w-1, y, remStr, _C.White)
        self.d.flip()

    def tick(self):
        isPlaying = self.ui.player.is_playing()
        if isPlaying or self.ui.shouldBePlaying:
            if not isPlaying:
                newIndex = self.ui.playlist.index + 1
                if self.ui.repeat and newIndex >= self.ui.playlist.count(): newIndex = 0
                if self.ui.selectSong(newIndex) >= 0: self.ui.playCurrent()
                else: self.ui.stopPlaying()
            self.paint()

class MainMenu(ListMenu):
    def __init__(self):
        super().__init__()
        self.sort = False

    def enter(self, firstTime):
        if not firstTime: self.refreshList()
        super().enter(firstTime)

    def getItems(self):
        d = {}
        if not self.ui.playlist.isempty(): d['Playlist'] = None
        d['Library'] = None
        d['Bluetooth' + (' (off)' if self.ui.isWifiEnabled else '')] = None
        d['Shuffle: ' + ('yes' if self.ui.shuffle else 'no')] = None
        d['Repeat: ' + ('yes' if self.ui.repeat else 'no')] = None
        d['Wifi: ' + ('on' if self.ui.isWifiEnabled else 'off')] = None
        d['System'] = None
        d['Exit'] = None
        return d

    def onPress(self, btn):
        if btn != _C.B or not self.ui.playlist.isempty(): super().onPress(btn)

    def onSelected(self, key, value, btn):
        if key == 'Playlist': self.ui.push(GroupMenu(self.ui.playlist.songs, playlist=True))
        elif key == 'Library': self.ui.push(LibraryMenu())
        elif key == 'Bluetooth': self.ui.push(BluetoothMenu())
        elif key == 'System': self.ui.push(SystemMenu())
        elif key == 'Exit': self.ui.exit()
        elif key.startswith('Shuffle'):
            self.ui.shuffle = not self.ui.shuffle
            self.ui.saveSettings()
            if self.ui.shuffle: self.ui.shuffleSongs(not self.ui.player.is_playing())
            self.refreshList(False)
        elif key.startswith('Repeat'):
            self.ui.repeat = not self.ui.repeat
            self.ui.saveSettings()
            self.refreshList(False)
        elif key.startswith('Wifi'):
            self.ui.enableWifi(not self.ui.isWifiEnabled)
            self.refreshList(False)

class SystemMenu(Menu):
    def __init__(self):
        super().__init__()
        self.ticks = 0

    def paint(self):
        self.d.clear()
        load = subprocess.run(['/usr/bin/uptime'], capture_output=True)
        load = re.search('load average:\s*([0-9]+(?:\.[0-9]*)?)', load.stdout.decode('utf-8'))
        mem = subprocess.run(['/usr/bin/free', '-wk'], capture_output=True)
        mem = re.search('Mem:\s*([0-9]+)\s+([0-9]+)', mem.stdout.decode('utf-8'))
        with open('/sys/class/thermal/thermal_zone0/temp') as f: temp = int(f.read())
        (y,h) = self.center(
            'Mem: ' + str(int(int(mem.group(2))/102.4+0.5)/10) + ' / ' + str(int(int(mem.group(1))/1024+0.5)) + ' MB', _C.White)
        load = self.measure('CPU load: ' + load.group(1))
        self.center(load, _C.White, y=y-load[0]-4)
        self.center('Temp: ' + str(int((temp*9//5+32050)//100)/10) + ' F', _C.White, y=y+h+4)
        self.d.flip()

    def onPress(self, btn):
        if btn == _C.B: self.ui.pop()

    def tick(self):
        self.ticks += 1
        if self.ticks % 5 == 0: self.paint() # repaint every 5 seconds

class LibraryMenu(ListMenu):
    def getItems(self):
        all = []
        for group in self.ui.library.groups.values(): all.extend(group.songs)
        d = dict(self.ui.library.groups)
        d[' All '] = library.Group('All', all) # HACK: spaces make it sort at the top...
        return d

    def onSelected(self, key, value, btn): self.ui.push(GroupMenu(value.songs))

class MusicMenu(ListMenu):
    def __init__(self, songs, playlist=False, trimNumbers=False):
        super().__init__()
        self.collapse = True
        self.songs = songs
        self.playlist = playlist
        self.trimNumbers = trimNumbers

    def onSelected(self, key, value, btn):
        if btn == _C.A: self.ui.push(PlayMenu(value, self.playlist, self.trimNumbers))

class ArtistMenu(MusicMenu):
    def getItems(self):
        d = {}
        for s in self.songs:
            L = d.get(s.artist)
            if not L: d[s.artist] = L = []
            L.append(s)
        return d

    def onSelected(self, artist, songs, btn):
        if btn == _C.A: super().onSelected(artist, songs, btn)
        else: self.ui.push(SongMenu(songs, trimNumbers=True))

class FolderMenu(MusicMenu):
    def getItems(self):
        d = {}
        for s in self.songs:
            folder = os.path.basename(os.path.dirname(s.path))
            L = d.get(folder)
            if not L: d[folder] = L = []
            L.append(s)
        return d

    def onSelected(self, artist, songs, btn):
        if btn == _C.A: super().onSelected(artist, songs, btn)
        else: self.ui.push(SongMenu(songs, self.playlist))

class GroupMenu(MusicMenu):
    def  __init__(self, songs, playlist=False):
        super().__init__(songs, playlist, trimNumbers=True)
        self.sort = False

    def getItems(self):
        d = {'All (Titles)':None, 'Artists':None, 'Find':None, 'Folders':None}
        if self.playlist: d['Clear'] = None
        return d

    def onSelected(self, key, value, btn):
        if key == 'Artists': self.ui.push(ArtistMenu(self.songs, self.playlist))
        elif key == 'Find': self.ui.push(FindMenu(self.songs, self.playlist))
        elif key == 'Folders': self.ui.push(FolderMenu(self.songs, self.playlist))
        elif key == 'Clear':
            self.ui.clearSongs()
            self.ui.pop()
        elif btn == _C.A and not self.playlist: super().onSelected(key, self.songs, btn)
        else: self.ui.push(SongMenu(self.songs, playlist=self.playlist, trimNumbers=True))

class PlayMenu(ListMenu):
    def __init__(self, songs, playlist=False, trimNumbers=False):
        super().__init__()
        self.sort = False
        self.songs = songs
        self.playlist = playlist
        self.trimNumbers = trimNumbers

    def getItems(self):
        return {'Enqueue and Play':None, 'Enqueue':None, 'Play':None} if not self.playlist else {'Play':None, 'Dequeue':None}

    def onSelected(self, key, value, btn):
        if key == 'Enqueue':
            self.ui.addSongs(self.songs, trimNumbers=self.trimNumbers)
            self.ui.pop()
        elif key == 'Dequeue':
            current = self.ui.playlist.getCurrent()
            self.ui.removeSongs(self.songs)
            if current is not None and not self.ui.playlist.contains(current) and self.ui.player.is_playing(): self.ui.playCurrent()
            self.ui.pop()
        else:
            self.ui.playSongs(self.songs, clear=(key=='Play' and not self.playlist), trimNumbers=self.trimNumbers)
            self.ui.popAll()

class SongMenu(MusicMenu):
    def getItems(self):
        d = {}
        for s in self.songs: d[_numRe.sub('', s.title) if self.trimNumbers else s.title] = s
        return d

    def onSelected(self, key, value, btn):
        if btn == _C.A: super().onSelected(key, value, btn)
        else: self.ui.playSongs(value, toggle=True)

class FindMenu(SongMenu):
    def __init__(self, songs, playlist=False):
        super().__init__(songs, playlist, trimNumbers=True)
        self.collapse = 'substr'

class UI:
    def __init__(self):
        self.repeat = True
        self.shuffle = True
        self.events = queue.Queue()
        self.display = display.Display(lambda btn: self.events.put(btn))
        self.display.power(True)
        self.smallFont = self.display.font.font_variant(size=16)
        self.bigFont = self.display.font.font_variant(size=30)
        self.stack = [LoadingMenu()]
        self.menu().init(self)
        self.library = library.Library('/home/pi/music')
        self.scanner = bluetooth.Scanner(onAdded=lambda s,d: self.btEvent(d, 'A'),
            onChanged=lambda s,d: self.btEvent(d, 'C'), onRemoved=lambda s,d: self.btEvent(d, 'R'))
        self.buttons = buttons.ButtonScanner(lambda btn: self.events.put(btn))

    def btEvent(self, dev, op): self.menu().onBtEvent(dev, op)
    def cleanup(self):
        self.buttons.stop()
        self.scanner.stop()
        self.display.cleanup()

    def clear(self): self.display.clear(_Background)

    def exit(self):
        signal.alarm(0) # cancel any pending alarm to prevent an error being printed if an alarm happens during shutdown
        self.cleanup()
        sys.exit(0)

    def menu(self): return self.stack[-1]

    def push(self, menu):
        self.menu().leave()
        self.stack.append(menu)
        menu.init(self)

    def pop(self):
        self.stack.pop().deinit()
        self.menu().enter(False)

    def popAll(self):
        if len(self.stack) > 1:
            while len(self.stack) > 1: self.stack.pop().deinit()
            self.menu().enter(False)

    def getMedia(self, song):
        return self.player.get_instance().media_new('file://' + urllib.parse.quote(self.library.getPath(song)))

    def ensureMedia(self, song=None, parse=True):
        media = None
        if song is None: song = self.playlist.getCurrent()
        if song:
            media = self.player.get_media()
            if not media:
                media = self.getMedia(song)
                if media: self.player.set_media(media)
            if parse and media: media.parse()
        return media

    def addSongs(self, songs, moveTo=False, trimNumbers=False):
        if type(songs) != library.Song:
            if self.shuffle:
                songs = list(songs)
                random.shuffle(songs)
            else:
                songs = list(sorted(songs, key=lambda s: s.artist.casefold() + "\n" + (s.title if not trimNumbers else _numRe.sub('', s.title)).casefold()))
        wasEmpty = self.playlist.isempty()
        first = self.playlist.add(songs, moveTo)
        if first:
            self.playlist.save()
            if moveTo or wasEmpty: self.saveSettings()
        return first

    def clearSongs(self):
        self.stopPlaying()
        self.playlist.clear()
        self.playlist.save()
        self.saveSettings()

    def removeSongs(self, songs):
        current = self.playlist.getCurrent()
        self.playlist.remove(songs)
        self.playlist.save()
        if current is not None and not self.playlist.contains(current):
            self.saveSettings()
            if self.player.is_playing(): self.playCurrent()

    def playCurrent(self, toggle=False):
        song = self.playlist.getCurrent()
        if song: self.playSong(song, toggle)
        else: self.stopPlaying()

    def playSong(self, song, toggle=False):
        url = 'file://' + urllib.parse.quote(self.library.getPath(song))
        currentMedia = self.player.get_media()
        if currentMedia is None or currentMedia.get_mrl() != url:
            media = self.player.get_instance().media_new(url)
            self.player.set_media(media)
            self._play()
        else:
            if not self.player.is_playing():
                # restart if we're at the end. vlc doesn't set position to 1 at the end, so it may be 0.998 or something
                tte = (1 - self.player.get_position()) * currentMedia.get_duration() # see how long that is in milliseconds
                # set_position doesn't work if the song is not playing, but it won't play if we're already at the end...
                if tte < 1000: self.player.stop() # so restart it by calling .stop()
                self._play()
            elif toggle:
                self._pause()

    def playSongs(self, songs, clear=False, trimNumbers=False, toggle=False):
        if clear: self.playlist.clear()
        self.playSong(self.addSongs(songs, moveTo=True, trimNumbers=trimNumbers), toggle)

    def previousTrack(self): return self._prevNextTrack(buttons.KEY_PREVIOUS)
    def nextTrack(self, canRewind=False): return self._prevNextTrack(buttons.KEY_NEXT, canRewind)

    def selectSong(self, song):
        index = self.playlist.index
        if self.playlist.select(song) and self.playlist.index != index: self.saveSettings()
        return self.playlist.index if not self.playlist.isempty() else -1

    def shuffleSongs(self, changeSong=False):
        self.playlist.shuffle(changeSong)
        if not changeSong and not self.playlist.isempty(): self.saveSettings()

    def stopPlaying(self):
        self.player.stop()
        self.shouldBePlaying = False

    def togglePlay(self):
        if not self.player.is_playing(): self._play()
        else: self._pause()

    def enableWifi(self, on):
        p = subprocess.run(['/usr/bin/sudo', '/usr/local/bin/' + ('revive' if on else 'kill') + '-wifi'])
        if p.returncode == 0:
            self.isWifiEnabled = on
            subprocess.run(['/usr/sbin/rfkill', 'block' if on else 'unblock', 'bluetooth'])

    def run(self):
        def sigint(sig, frame): self.exit()
        def sigalarm(sig, frame):
            self.events.put(0)
            signal.alarm(1)
        signal.signal(signal.SIGINT, sigint)
        signal.signal(signal.SIGALRM, sigalarm)
        self.scanner.start()
        self.library.scan()
        self.playlist = library.Playlist('/home/pi/music/playlist', self.library)
        self.player = vlc.MediaPlayer()
        self.buttons.start()

        try:
            with open('/home/pi/.player') as f:
                settings = json.loads(f.read())
                self.repeat = settings.get('repeat', self.repeat)
                self.shuffle = settings.get('shuffle', self.shuffle)
                song = settings.get('song')
                if song: self.playlist.select(song)
        except: pass

        self.shouldBePlaying = False
        self.isWifiEnabled = self._checkWifiEnabled()
        self.stack.pop().leave()
        self.stack.append(RootMenu())
        self.menu().init(self)
        signal.alarm(1)
        while True: # TODO: now that we have a queue, collapse painting together, etc
            e = self.events.get()
            if e == 0: self.tick()
            elif e <= 40: self.menu().onPress(e)
            else: self._mediaButton(e)

    def saveSettings(self):
        settings = {'repeat':self.repeat, 'shuffle':self.shuffle}
        song = self.playlist.getCurrent()
        if song: settings['song'] = song.path
        with open('/home/pi/.player', 'w') as f: f.write(json.dumps(settings))

    def tick(self): self.menu().tick()

    def _checkWifiEnabled(self):
        p = subprocess.run(['/usr/sbin/rfkill', '--json'], capture_output=True)
        if p.returncode == 0:
            o = json.loads(p.stdout)
            for r in o.get('', []):
                if r['type'] == 'wlan': return r['soft'] == 'unblocked' and r['hard'] == 'unblocked'
        return False

    def _mediaButton(self, btn):
        if btn == buttons.KEY_PREVIOUS or btn == buttons.KEY_NEXT: self._prevNextTrack(btn, True)
        elif btn == buttons.KEY_PLAY: self.playCurrent()
        elif btn == buttons.KEY_PAUSE: self._pause()
        elif btn == buttons.KEY_STOP: self._stop()
        elif btn == buttons.KEY_PLAYPAUSE:
            if self.player.is_playing(): self._pause()
            else: self.playCurrent()

    def _pause(self):
        self.player.pause()
        self.shouldBePlaying = False

    def _play(self):
        self.player.play()
        self.shouldBePlaying = True

    def _prevNextTrack(self, btn, canRewind=False):
        changed = False
        rewind = False
        if canRewind and btn == buttons.KEY_PREVIOUS and self.shouldBePlaying:
            media = self.ensureMedia()
            rewind = media and media.get_duration() * self.player.get_position() > 5000
        if rewind:
            self.player.set_position(0)
            changed = True
        else:
            oldIndex = self.playlist.index
            newIndex = oldIndex + (-1 if btn == buttons.KEY_PREVIOUS else 1)
            if newIndex < 0: newIndex = self.playlist.count() - 1
            elif newIndex >= self.playlist.count(): newIndex = 0
            if self.selectSong(newIndex) != oldIndex:
                if self.player.is_playing(): self.playCurrent()
                changed = True

        if changed and type(self.menu()) == RootMenu: self.menu().paint()

UI().run()
