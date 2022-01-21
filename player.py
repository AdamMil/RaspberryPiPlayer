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
import time
import urllib.parse
import vlc

_C = display.Display
_Background = _C.Black
_Selected = _C.White
_Unselected = _C.Gray
_numRe = re.compile('^[0-9]+ - ')

class Menu:
    def __init__(self): self.headerSize = 0
    def deinit(self): self.leave()
    def init(self, ui):
        self.ui = ui
        self.d = ui.display
        self.enter(True)
    def enter(self, firstTime): self.paint()
    def leave(self): pass
    def onBluetoothEvent(self, dev, op): pass
    def onPress(self, btn): pass
    def paint(self):
        self.ui.clear()
        self.paintCore()
        self.d.flip()
    def paintCore(self): pass
    def tick(self): pass

    def center(self, item, color, font=None, y=None):
        if type(item) == str: item = self.measure(item, font)
        if y is None: y = (self.d.height - self.headerSize - item[0]) // 2 + self.headerSize
        startY = max(self.headerSize, y)
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
    def paintCore(self): self.d.center('Loading...', _C.White)

class ListMenu(Menu):
    class _collapsed:
        def __init__(self, keys, group=None):
            self.keys = keys
            self.group = group

    def __init__(self):
        super().__init__()
        self.collapse = False
        self.sort = False
        self.keepIndex = False
        self.keys = None
        self.index = 0
        self.stack = None

    def enter(self, firstTime):
        if firstTime: self.refreshList(False)
        super().enter(firstTime)

    def getColor(self, key): return _Selected
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

    def paintCore(self):
        if len(self.keys):
            Spacing = 4
            (y,h) = self.center(self.keys[self.index], self.getColor(self.keys[self.index]))
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
                if depth: letters = " '" + letters
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
                    if len(L) > 2 and count > threshold:
                        key = '...' + bucket.upper() + '...'
                        self.keys.append(key)
                        self.items[key] = ListMenu._collapsed(L, bucket)
                        count += 1
                        for k in L:
                            if k not in dedup:
                                dedup[k] = None
                                count -= 1
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
    def __init__(self): self.sort = True

    def deinit(self):
        self.ui.scanner.stopScan()
        super().deinit()

    def init(self, ui):
        super().init(ui)
        self.ui.scanner.startScan()

    def getItems(self):
        devices = {dev.name: dev.addr for dev in self.ui.scanner.devices.values() if self._isAudioSink(dev)}
        return devices if len(devices) != 0 else {'Scanning...': None}

    def onBluetoothEvent(self, dev, op): self.refreshList()

    def onSelected(self, key, value, btn):
        if value is not None: self.ui.push(DeviceMenu(value))

    def _isAudioSink(self, dev):
        return bluetooth.AUDIO_SINK in dev.uuids if len(dev.uuids) else (dev.cls & 0x200400) == 0x200400

class DeviceMenu(ListMenu):
    def __init__(self, addr):
        super().__init__()
        self.addr = addr
        self.keepIndex = True

    def getItems(self):
        dev = self._getDevice()
        if dev is None:
            self.ui.pop()
            return {}
        return {'Disconnect' if dev.connected else 'Connect': None,
                'Forget' if dev.paired else 'Pair': None,
                'Untrust' if dev.trusted else 'Trust': None}

    def onBluetoothEvent(self, dev, op):
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
            if btn == _C.U: self.ui.previousTrack(canRewind=True)
            elif btn == _C.D: self.ui.nextTrack()
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

    def paintCore(self):
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

    def tick(self):
        if not self.ui.pendingPlay:
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
        self.locked = False
        self.keepIndex = True

    def enter(self, firstTime):
        if not firstTime: self.refreshList()
        super().enter(firstTime)

    def getColor(self, key):
        if self.locked: return _C.Orange
        elif self.ui.isWifiEnabled and key.startswith('Bluetooth'): return (160,160,160)
        else: return super().getColor(key)

    def getItems(self):
        d = {}
        if not self.ui.playlist.isempty(): d['Playlist'] = None
        d['Library'] = None
        d['Bluetooth' + (' (off)' if self.ui.isWifiEnabled else '')] = None
        d['Shuffle: ' + ('yes' if self.ui.shuffle else 'no')] = None
        d['Repeat: ' + ('yes' if self.ui.repeat else 'no')] = None
        d['Volume: ' + str(self.ui.volume)] = None
        d['Wifi: ' + ('on' if self.ui.isWifiEnabled else 'off')] = None
        for k in ('System','Sleep','Exit'): d[k] = None
        return d

    def onPress(self, btn):
        if self.locked:
            if btn == _C.A or btn == _C.B or btn == _C.C:
                self.locked = False
                self.paint()
            else:
                newVolume = self.ui.volume
                if btn == _C.U: newVolume += 10
                elif btn == _C.D: newVolume -= 10
                elif btn == _C.L: newVolume -= 30
                elif btn == _C.R: newVolume += 30
                newVolume = max(0, min(100, (newVolume+5)//10*10))
                if newVolume != self.ui.volume:
                    self.ui.setVolume(newVolume)
                    self.ui.saveSettings()
                    self.refreshList()
        elif btn != _C.B or not self.ui.playlist.isempty():
            super().onPress(btn)

    def onSelected(self, key, value, btn):
        if key == 'Playlist': self.ui.push(GroupMenu(self.ui.playlist.songs, playlist=True))
        elif key == 'Library':
            if len(self.ui.library.groups) != 1: self.ui.push(LibraryMenu())
            else: self.ui.push(GroupMenu(next(iter(self.ui.library.groups.values())).songs))
        elif key == 'Bluetooth': self.ui.push(BluetoothMenu())
        elif key == 'System': self.ui.push(SystemMenu())
        elif key == 'Sleep': self.ui.sleep()
        elif key == 'Exit': self.ui.exit()
        elif key.startswith('Shuffle'):
            self.ui.shuffle = not self.ui.shuffle
            self.ui.saveSettings()
            if self.ui.shuffle: self.ui.shuffleSongs(not self.ui.player.is_playing())
            self.refreshList()
        elif key.startswith('Repeat'):
            self.ui.repeat = not self.ui.repeat
            self.ui.saveSettings()
            self.refreshList()
        elif key.startswith('Volume'):
            self.locked = True
            self.paint()
        elif key.startswith('Wifi'):
            self.ui.enableWifi(not self.ui.isWifiEnabled)
            self.refreshList()

class SystemMenu(Menu):
    def __init__(self):
        super().__init__()
        self.ticks = 0

    def paintCore(self):
        freq = subprocess.run(['/usr/bin/vcgencmd', 'measure_clock', 'arm'], capture_output=True)
        freq = int(re.search('=([0-9]+)$', freq.stdout.decode('ascii')).group(1))
        load = subprocess.run(['/usr/bin/uptime'], capture_output=True)
        load = re.search('load average:\s*([0-9]+(?:\.[0-9]*)?)', load.stdout.decode('ascii')).group(1)
        mem = subprocess.run(['/usr/bin/free', '-wk'], capture_output=True)
        mem = re.search('Mem:\s*([0-9]+)\s+([0-9]+)', mem.stdout.decode('ascii'))
        flags = subprocess.run(['/usr/bin/vcgencmd', 'get_throttled'], capture_output=True)
        flags = int(re.search('=0x([0-9]+)$', flags.stdout.decode('ascii')).group(1), 16)
        with open('/sys/class/thermal/thermal_zone0/temp') as f: temp = int(f.read())
        (y,h) = self.center(
            'Mem: ' + str(int(int(mem.group(2))/102.4+0.5)/10) + ' / ' + str(int(int(mem.group(1))/1024+0.5)) + ' MB', _C.White)
        load = self.measure('CPU: ' + load + ' @ ' + str((freq+5000000)//10000000/100) + ' ghz')
        self.center(load, _C.White, y=y-load[0]-4)
        color = _C.White if temp < 60000 else _C.Yellow if temp < 70000 else _C.Orange if temp < 80000 else _C.Red
        d = self.center('Temp: ' + str(int((temp*9//5+32500)//1000)) + ' F (' + str(int(temp+500)//1000) + ' C)', color, y=y+h+4)
        if flags & 0xF000F:
            def decode(f):
                s = ''
                if f & 2: s += 'F'
                if f & 8: s += 'H'
                if f & 4: s += 'T'
                if f & 1: s += 'V'
                return s
            color = _C.Red if flags & 9 else _C.Orange if flags & 0x90000 else _C.Yellow if flags & 6 else _C.White
            self.center('Flags: ' + decode(flags) + decode(flags >> 16).lower(), color, y=d[0]+d[1]+4)

    def onPress(self, btn):
        if btn == _C.B: self.ui.pop()

    def tick(self):
        self.ticks += 1
        if self.ticks % 5 == 0: self.paint() # repaint every 5 seconds

class MusicMenu(ListMenu):
    def __init__(self, songs, playlist=False, trimNumbers=False):
        super().__init__()
        self.collapse = True
        self.songs = songs
        self.sort = True
        self.playlist = playlist
        self.trimNumbers = trimNumbers

    def onSelected(self, key, value, btn):
        if btn == _C.A:
            if type(value) == library.Group: value = value.songs
            if type(value) == library.Song or len(value) == 1:
                song = value if type(value) == library.Song else value[0]
                h1 = song.artist
                h2 = song.title
            else:
                h1 = str(len(value)) + ' song' + ('s' if len(value) > 1 else '')
                h2 = key
            self.ui.push(PlayMenu(value, h1, h2, self.playlist, trimNumbers=self.trimNumbers))

class LibraryMenu(MusicMenu):
    def __init__(self):
        super().__init__(None)
        self.sort = False

    def getItems(self):
        all = []
        for group in self.ui.library.groups.values(): all.extend(group.songs)
        d = {'All': library.Group('All', all)}
        for g in sorted(self.ui.library.groups.values(), key=lambda g: g.name): d[g.name] = g
        return d

    def onSelected(self, key, value, btn):
        if btn == _C.A: super().onSelected(key, value, btn)
        else: self.ui.push(GroupMenu(value.songs))

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

    def onSelected(self, folder, songs, btn):
        if btn == _C.A: super().onSelected(folder, songs, btn)
        else: self.ui.push(SongMenu(songs, self.playlist))

class GroupMenu(MusicMenu):
    def  __init__(self, songs, playlist=False):
        super().__init__(songs, playlist, trimNumbers=True)
        self.sort = False

    def getItems(self):
        d = {}
        if self.playlist:
            d['Show'] = None
            d['Titles'] = None
        else:
            d['All (Titles)'] = None
        for k in ('Artists','Find','Folders'): d[k] = None
        if self.playlist: d['Clear'] = None
        return d

    def onSelected(self, key, value, btn):
        if key == 'Artists': self.ui.push(ArtistMenu(self.songs, self.playlist))
        elif key == 'Find': self.ui.push(FindMenu(self.songs, self.playlist))
        elif key == 'Folders': self.ui.push(FolderMenu(self.songs, self.playlist))
        elif key == 'Clear':
            self.ui.clearSongs()
            self.ui.pop()
        elif key == 'Show':
            menu = SongMenu(self.songs, playlist=self.playlist)
            menu.sort = menu.collapse = False
            menu.keepIndex = True
            menu.index = self.ui.playlist.index
            self.ui.push(menu)
        elif btn == _C.A and not self.playlist: super().onSelected(None, self.songs, btn)
        else: self.ui.push(SongMenu(self.songs, playlist=self.playlist, trimNumbers=True))

class PlayMenu(ListMenu):
    def __init__(self, songs, h1=None, h2=None, playlist=False, trimNumbers=False):
        super().__init__()
        self.songs = songs
        self.playlist = playlist
        self.trimNumbers = trimNumbers
        self.h1 = h1
        self.h2 = h2

    def enter(self, firstTime):
        if firstTime:
            if self.h1:
                self.h1Dims = self.d.textsize(self.h1)
                self.headerSize = self.h1Dims[1] + 1
                if self.h2: self.headerSize += 2
            if self.h2:
                self.h2 = self.measure(self.h2, self.ui.bigFont)
                if len(self.h2[1]) > 3: # only show the first three lines of the header to leave space for the menu
                    self.h2 = (self.h2[1][0][2] + self.h2[1][1][2] + self.h2[1][2][2], self.h2[1][0:3])
                self.headerSize += self.h2[0]
        super().enter(firstTime)

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

    def paintCore(self):
        y = 1
        if self.h1:
            self.d.text(max(0, (self.d.width-self.h1Dims[0]) // 2), 1, self.h1, _C.Gray)
            y += self.h1Dims[1] + 2
        if self.h2: self.center(self.h2, _C.White, self.ui.bigFont, y)
        super().paintCore()

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
        self.sleeping = False
        self.events = queue.Queue()
        self.display = display.Display(lambda btn: self.events.put(btn))
        self.display.power(True)
        self.smallFont = self.display.font.font_variant(size=16)
        self.bigFont = self.display.font.font_variant(size=30)
        self.stack = [LoadingMenu()]
        self.menu().init(self)
        self.library = library.Library('/home/pi/music')
        self.scanner = bluetooth.Scanner(onAdded=lambda s,d: self.bluetoothEvent(d, 'A'),
            onChanged=lambda s,d: self.bluetoothEvent(d, 'C'), onRemoved=lambda s,d: self.bluetoothEvent(d, 'R'))
        self.buttons = buttons.ButtonScanner(lambda btn: self.events.put(btn))

    def bluetoothEvent(self, dev, op): self.menu().onBluetoothEvent(dev, op)
    def cleanup(self):
        self.buttons.stop()
        self.scanner.stop()
        self.display.cleanup()

    def clear(self): self.display.clear(_Background)

    def exit(self):
        signal.alarm(0) # cancel any pending alarm to prevent an error being printed if an alarm happens during shutdown
        if self.sleeping: self.enableWifi(self.isWifiEnabled) # restore networking
        self.cleanup()
        sys.exit(0)

    def menu(self): return self.stack[-1]

    def onPress(self, btn):
        self.idleTicks = 0
        if self.sleeping: self.wake()
        else: self.menu().onPress(btn)

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
                self.pausePlaying()

    def playSongs(self, songs, clear=False, trimNumbers=False, toggle=False):
        if clear: self.playlist.clear()
        self.playSong(self.addSongs(songs, moveTo=True, trimNumbers=trimNumbers), toggle)

    def pausePlaying(self):
        self.player.pause()
        self.shouldBePlaying = False
        self.pendingPlay = 0

    def previousTrack(self, canRewind=False): return self._prevNextTrack(buttons.KEY_PREVIOUS, canRewind)
    def nextTrack(self): return self._prevNextTrack(buttons.KEY_NEXT)

    def selectSong(self, song):
        index = self.playlist.index
        if self.playlist.select(song) and self.playlist.index != index: self.saveSettings()
        return self.playlist.index if not self.playlist.isempty() else -1

    def setVolume(self, volume):
        volume = max(0, min(100, volume))
        if volume != self.volume:
            self.player.audio_set_volume(volume)
            self.volume = volume

    def shuffleSongs(self, changeSong=False):
        self.playlist.shuffle(changeSong)
        if not changeSong and not self.playlist.isempty(): self.saveSettings()

    def sleep(self):
        self.sleeping = True
        signal.alarm(0) # cancel pending alarms
        self.pausePlaying()
        subprocess.run(['/usr/bin/sudo', '/usr/local/bin/kill-wifi'])
        subprocess.run(['/usr/sbin/rfkill', 'block', 'bluetooth'])
        self.display.power(False)

    def wake(self):
        self.sleeping = False
        signal.alarm(1) # resume alarms
        self.enableWifi(self.isWifiEnabled)
        self.display.power(True)

    def stopPlaying(self):
        self.player.stop()
        self.shouldBePlaying = False
        self.pendingPlay = 0

    def togglePlay(self):
        if not self.player.is_playing(): self._play()
        else: self.pausePlaying()

    def enableWifi(self, on):
        p = subprocess.run(['/usr/bin/sudo', '/usr/local/bin/' + ('revive' if on else 'kill') + '-wifi'])
        if p.returncode == 0:
            self.isWifiEnabled = on
            subprocess.run(['/usr/sbin/rfkill', 'block' if on else 'unblock', 'bluetooth'])

    def run(self):
        def shutdown(sig, frame): self.exit()
        def onalarm(sig, frame):
            if not self.sleeping:
                self.events.put(0)
                signal.alarm(1)
        signal.signal(signal.SIGALRM, onalarm)
        signal.signal(signal.SIGHUP, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGCONT, lambda s,f: self.events.put(buttons.KEY_PLAYPAUSE))
        signal.signal(signal.SIGUSR1, lambda s,f: self.events.put(buttons.KEY_PREVIOUS))
        signal.signal(signal.SIGUSR2, lambda s,f: self.events.put(buttons.KEY_NEXT))
        self.scanner.start()
        self.library.scan()
        self.playlist = library.Playlist('/home/pi/music/playlist', self.library)
        self.player = vlc.MediaPlayer()
        self.buttons.start()
        self.idleTicks = 0
        self.volume = 100

        try:
            with open('/home/pi/.player') as f:
                settings = json.loads(f.read())
                self.repeat = settings.get('repeat', self.repeat)
                self.shuffle = settings.get('shuffle', self.shuffle)
                self.volume = max(0, min(100, settings.get('volume', 100)))
                song = settings.get('song')
                if song: self.playlist.select(song)
        except: pass

        self.player.audio_set_volume(self.volume)
        self.pendingPlay = 0
        self.shouldBePlaying = False
        self.isWifiEnabled = self._checkWifiEnabled()
        self.stack.pop().leave()
        self.stack.append(RootMenu())
        self.menu().init(self)
        signal.alarm(1)
        while True: # TODO: now that we have a queue, collapse painting together, etc
            e = self.events.get()
            if e == 0: self.tick()
            elif e <= 40: self.onPress(e)
            else: self._mediaButton(e)

    def saveSettings(self):
        settings = {'repeat':self.repeat, 'shuffle':self.shuffle, 'volume':self.volume}
        song = self.playlist.getCurrent()
        if song: settings['song'] = song.path
        with open('/home/pi/.player', 'w') as f: f.write(json.dumps(settings))

    def tick(self):
        self.menu().tick()
        if self.pendingPlay and time.monotonic() >= self.pendingPlay:
            self.playCurrent()
            self._repaint(RootMenu)
        elif not self.shouldBePlaying and not self.pendingPlay:
            self.idleTicks += 1
            if self.idleTicks == 180: self.sleep() # go to sleep after 3 minutes of idleness

    def _checkWifiEnabled(self):
        p = subprocess.run(['/usr/sbin/rfkill', '--json'], capture_output=True)
        if p.returncode == 0:
            o = json.loads(p.stdout)
            for r in o.get('', []):
                if r['type'] == 'wlan': return r['soft'] == 'unblocked' and r['hard'] == 'unblocked'
        return False

    def _mediaButton(self, btn):
        self.idleTicks = 0
        if self.sleeping: self.wake()
        if btn == buttons.KEY_PREVIOUS or btn == buttons.KEY_NEXT: self._prevNextTrack(btn, True)
        elif btn == buttons.KEY_PLAY: self.playCurrent()
        elif btn == buttons.KEY_PAUSE: self.pausePlaying()
        elif btn == buttons.KEY_STOP: self.stopPlaying()
        elif btn == buttons.KEY_PLAYPAUSE:
            if self.player.is_playing(): self.pausePlaying()
            else: self.playCurrent()

    def _play(self):
        self.player.play()
        self.shouldBePlaying = True
        self.pendingPlay = 0

    def _prevNextTrack(self, btn, canRewind=False):
        changed = False
        rewind = False
        if canRewind and btn == buttons.KEY_PREVIOUS and not self.pendingPlay and self.shouldBePlaying:
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
                changed = True
                if self.shouldBePlaying: self.pendingPlay = time.monotonic() + 1.5

        if changed: self._repaint(RootMenu)

    def _repaint(self, menuType): # yuck?
         if isinstance(self.menu(), menuType): self.menu().paint()

UI().run()
