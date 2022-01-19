import os
import random
import re
import stat

_numRe = re.compile(r'^\s*[0-9]+\s*$')
_songRe = re.compile(r"^\s*(.+?)\s+-\s+(.+?)\.[^\.]+$", re.S)
_exts = {e:None for e in ['aac','aiff','alac','au','flac','m4a','m4b','mp3','oga','ogg','opus','ra','rm','wav','webm','wma']}

class Group:
    def __init__(self, name, songs):
        self.name = name
        self.songs = songs
    def __str__(self): return self.name

class Song:
    def __init__(self, path, artist, title):
        self.path = path
        self.artist = artist
        self.title = title
    def __str__(self): return self.artist + ' - ' + self.title

class Library:
    def __init__(self, root):
        self.root = root
        self.groups = None

    def __str__(self): return self.root

    def getPath(self, song): return os.path.join(self.root, song.path)

    def scan(self):
        self.groups = {}
        for name in os.listdir(self.root):
            s = os.stat(os.path.join(self.root, name))
            if stat.S_ISDIR(s.st_mode):
                self.groups[name] = self._scanGroup(name)

    def _scanGroup(self, name):
        return Group(name, Library._scanSongs(self.root, name, []))

    @staticmethod
    def _scanSongs(root, rel, songs):
        dir = os.path.join(root, rel)
        for name in os.listdir(dir):
            s = os.stat(os.path.join(dir, name))
            if stat.S_ISDIR(s.st_mode):
                Library._scanSongs(root, rel+'/'+name, songs)
            else:
                (base, ext) = os.path.splitext(name)
                if ext[1:].lower() in _exts:
                    m = _songRe.fullmatch(name)
                    if not m:
                        (artist, title) = ('Unknown', base)
                    else:
                        (artist, title) = m.groups()
                        if _numRe.search(artist): # if 'artist' is a number, get it from the directory
                            slash = rel.find('/') # strip the group name off the front
                            if slash >= 0: (artist, title) = (os.path.basename(rel[slash+1:]), artist + ' - ' + title)
                            else: artist = 'Unknown'
                    songs.append(Song(rel+'/'+name, artist, title))
        return songs

class Playlist:
    def __init__(self, playlistFile, library):
        self.songs = []
        self.paths = {}
        self.index = 0
        if playlistFile:
            if library:
                try:
                    with open(playlistFile) as file:
                        songsByPath = {}
                        for g in library.groups.values():
                            for s in g.songs: songsByPath[s.path] = s
                        while True:
                            line = file.readline()
                            if not line: break
                            song = songsByPath.get(line[0:-1]) # strip \n
                            if song:
                                self.paths[song.path] = len(self.songs)
                                self.songs.append(song)
                except FileNotFoundError: pass
                self.index = max(0, min(self.index, len(self.songs)-1))
            self.playlistFile = playlistFile

    def add(self, songs, moveTo=False):
        if type(songs) == Song: songs = (songs,)
        elif type(songs) == Group: songs = songs.songs
        firstSong = None
        for song in songs:
            if firstSong is None: firstSong = song
            if song.path not in self.paths:
                if moveTo: self.index = len(self.songs)
                self.paths[song.path] = len(self.songs)
                self.songs.append(song)
            elif moveTo: self.index = self.paths[song.path]
            moveTo = False
        return firstSong

    def clear(self):
        self.songs.clear()
        self.paths.clear()
        self.index = 0

    def remove(self, songs):
        if type(songs) == Song: songs = (songs,)
        elif type(songs) == Group: songs = songs.songs
        if len(songs) == 1:
            index = self.paths.get(songs[0].path)
            if index >= 0:
                self.paths.pop(songs[0].path)
                self.songs.remove(self.songs[index])
                if index == self.index and index == len(self.songs): self.index -= 1
                for p,i in self.paths.items():
                    if i > index: self.paths[p] -= 1
        else:
            for song in songs:
                index = self.paths.get(song.path)
                if index >= 0:
                    self.paths.pop(song.path)
                    if index > self.index or index == len(self.songs): self.index -= 1
            L = [self.songs[i] for i in self.paths.values()]
            self.paths = {L[i].path:i for i in range(len(L))}
            self.songs.clear() # avoid changing the self.songs reference, since others may have a reference to it
            self.songs.extend(L)
        if not self._validIndex(): self.index = 0

    def contains(self, song): return song.path in self.paths
    def count(self): return len(self.songs)
    def getCurrent(self): return self.songs[self.index] if self._validIndex() else None
    def isempty(self): return len(self.songs) == 0

    def save(self, playlistFile=None):
        if playlistFile is None: playlistFile = self.playlistFile
        with open(playlistFile, 'w') as file:
            for s in self.songs: file.write(s.path + "\n")

    def select(self, item):
        newIndex = item
        if isinstance(item, Song): newIndex = self.paths.get(song.path)
        elif isinstance(item, str): newIndex = self.paths.get(item)
        if newIndex is None or newIndex < 0 or newIndex >= len(self.songs): return False
        self.index = newIndex
        return True

    def shuffle(self, changeSong=False):
        i = 0
        while i < len(self.songs):
            j = random.randint(i, len(self.songs)-1)
            if i != j:
                (a, b) = (self.songs[i], self.songs[j])
                (self.songs[i], self.songs[j], self.paths[a.path], self.paths[b.path]) = (b, a, j, i)
                if not changeSong:
                    if self.index == i: self.index = j
                    elif self.index == j: self.index = i
            i += 1

    def _validIndex(self): return self.index >= 0 and self.index < len(self.songs)
